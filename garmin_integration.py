from __future__ import annotations

import datetime
import logging
import os
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Optional

from garminconnect import (
    Garmin,
    GarminConnectAuthenticationError,
    GarminConnectConnectionError,
    GarminConnectTooManyRequestsError,
)

logger = logging.getLogger(__name__)

@dataclass
class GarminActivity:
    """
    Normalized activity record — captures every field from
    get_activities_by_date / get_activities (Activity + ActivityType models).
    """
    activity_id: str
    activity_name: str
    activity_type: str

    # Activity type metadata
    activity_type_id: Optional[int] = None
    activity_type_parent_id: Optional[int] = None
    activity_type_hidden: Optional[bool] = None

    # Timestamps
    start_time_local: Optional[str] = None
    start_time_gmt: Optional[str] = None

    # Duration
    duration_seconds: Optional[float] = None
    moving_duration_seconds: Optional[float] = None
    elapsed_duration_seconds: Optional[float] = None

    # Distance & elevation
    distance_meters: Optional[float] = None
    elevation_gain: Optional[float] = None
    elevation_loss: Optional[float] = None

    # Speed & pace
    avg_speed_mps: Optional[float] = None
    max_speed_mps: Optional[float] = None
    avg_pace_min_per_km: Optional[float] = None   # derived

    # Heart rate
    avg_heart_rate: Optional[float] = None
    max_heart_rate: Optional[float] = None

    # Calories
    calories: Optional[float] = None
    bmr_calories: Optional[float] = None

    # Power
    avg_power: Optional[float] = None
    max_power: Optional[float] = None
    normalized_power: Optional[float] = None

    # Training load & effect
    training_effect_aerobic: Optional[float] = None
    training_effect_anaerobic: Optional[float] = None
    activity_training_load: Optional[float] = None
    training_effect_label: Optional[str] = None

    # Cadence (running)
    avg_running_cadence: Optional[float] = None
    max_running_cadence: Optional[float] = None

    # Strength-specific
    total_sets: Optional[int] = None
    active_sets: Optional[int] = None
    total_reps: Optional[int] = None
    total_volume: Optional[float] = None

    # IDs
    device_id: Optional[str] = None
    gear_id: Optional[str] = None

    # Metadata
    ingested_at: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


class GarminClient:
    """
    High-level Garmin Connect API client.
    """

    def __init__(
        self,
        email: Optional[str] = None,
        password: Optional[str] = None,
        token_store: Optional[str] = None,
        max_retries: int = 3,
        retry_delay: float = 2.0,
    ):
        self.email = email or os.environ.get("GARMIN_EMAIL", "")
        self.password = password or os.environ.get("GARMIN_PASSWORD", "")
        self.token_store = token_store or os.environ.get(
            "GARMIN_TOKEN_STORE", os.path.expanduser("~/.garminconnect")
        )
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self._api: Optional[Garmin] = None

    def connect(self) -> None:
        tokenstore = Path(self.token_store)
        if tokenstore.exists():
            try:
                self._api = Garmin()
                logger.info("Attempting token-based login from %s", tokenstore)
                self._api.login(str(tokenstore))
                logger.info("Token login successful")
                return
            except Exception as exc:
                logger.warning("Token login failed (%s), falling back to credentials", exc)

        if not self.email or not self.password:
            raise ValueError(
                "GARMIN_EMAIL and GARMIN_PASSWORD must be set when no valid token exists"
            )
        self._api = Garmin(self.email, self.password)
        self._api.login()
        tokenstore.parent.mkdir(parents=True, exist_ok=True)
        self._api.garth.dump(str(tokenstore))
        logger.info("Credential login successful — tokens saved to %s", tokenstore)

    def _call(self, fn, *args, **kwargs) -> Any:
        for attempt in range(self.max_retries):
            try:
                return fn(*args, **kwargs)
            except GarminConnectTooManyRequestsError:
                wait = self.retry_delay * (2 ** attempt)
                time.sleep(wait)
            except GarminConnectConnectionError:
                if attempt == self.max_retries - 1:
                    raise
                time.sleep(self.retry_delay)
            except GarminConnectAuthenticationError:
                raise
        return None

    def _normalize_activity(self, r: dict) -> GarminActivity:
        at = r.get("activityType") or {}
        a = GarminActivity(
            activity_id               = str(r.get("activityId", "")),
            activity_name             = r.get("activityName", ""),
            activity_type             = at.get("typeKey", "unknown"),
            activity_type_id          = at.get("typeId"),
            activity_type_parent_id   = at.get("parentTypeId"),
            activity_type_hidden      = at.get("isHidden"),
            start_time_local          = r.get("startTimeLocal"),
            start_time_gmt            = r.get("startTimeGMT"),
            duration_seconds          = r.get("duration"),
            moving_duration_seconds   = r.get("movingDuration"),
            elapsed_duration_seconds  = r.get("elapsedDuration"),
            distance_meters           = r.get("distance"),
            elevation_gain            = r.get("elevationGain"),
            elevation_loss            = r.get("elevationLoss"),
            avg_speed_mps             = r.get("averageSpeed"),
            max_speed_mps             = r.get("maxSpeed"),
            avg_heart_rate            = r.get("averageHR"),
            max_heart_rate            = r.get("maxHR"),
            calories                  = r.get("calories"),
            bmr_calories              = r.get("bmrCalories"),
            avg_power                 = r.get("avgPower"),
            max_power                 = r.get("maxPower"),
            normalized_power          = r.get("normPower"),
            training_effect_aerobic   = r.get("aerobicTrainingEffect"),
            training_effect_anaerobic = r.get("anaerobicTrainingEffect"),
            activity_training_load    = r.get("activityTrainingLoad"),
            training_effect_label     = r.get("trainingEffectLabel"),
            avg_running_cadence       = r.get("averageRunningCadenceInStepsPerMinute"),
            max_running_cadence       = r.get("maxRunningCadenceInStepsPerMinute"),
            total_sets                = r.get("totalSets"),
            active_sets               = r.get("activeSets"),
            total_reps                = r.get("totalReps"),
            total_volume              = r.get("totalVolume"),
            ingested_at               = datetime.datetime.utcnow().isoformat(),
        )
        if a.avg_speed_mps and a.avg_speed_mps > 0:
            a.avg_pace_min_per_km = (1000 / a.avg_speed_mps) / 60
        return a

    def get_activities_for_date_range(
        self,
        start_date: datetime.date,
        end_date: datetime.date,
        activity_type: Optional[str] = None,
    ) -> list[GarminActivity]:
        raw = self._call(
            self._api.get_activities_by_date,
            start_date.isoformat(),
            end_date.isoformat(),
            activity_type,
        ) or []
        return [self._normalize_activity(r) for r in raw]

GARMIN_TYPE_MAP = {
    "Strength": "健身",
    "Walking": "走路",
    "Treadmill Running": "健身房跑步機"
}

def sync_garmin_activities(bq_client, table_id, days=3):
    """
    Fetch Garmin activities and sync them to BigQuery.
    """
    client = GarminClient()
    try:
        client.connect()
    except Exception as e:
        return f"Error connecting to Garmin: {e}"

    end_date = datetime.date.today()
    start_date = end_date - datetime.timedelta(days=days)
    
    activities = client.get_activities_for_date_range(start_date, end_date)
    
    if not activities:
        return "No Garmin activities found in the last few days."

    # Fetch existing Garmin activity IDs from BigQuery to avoid duplicates
    query = f"""
        SELECT id
        FROM `{table_id}`
        WHERE id LIKE 'garmin_%'
    """
    try:
        existing_df = bq_client.query(query).to_dataframe()
        existing_ids = set(existing_df['id'].tolist()) if not existing_df.empty else set()
    except Exception as e:
        logger.warning(f"Could not fetch existing IDs: {e}")
        existing_ids = set()

    rows_to_insert = []
    synced_count = 0
    
    for act in activities:
        act_id = f"garmin_{act.activity_id}"
        if act_id in existing_ids:
            continue
            
        habit_name = GARMIN_TYPE_MAP.get(act.activity_name, "健身")
        
        # Garmin start_time_local is usually "YYYY-MM-DD HH:MM:SS"
        start_time_iso = act.start_time_local.replace(" ", "T")
        
        # Create end_time from start_time + duration
        try:
            start_dt = datetime.datetime.fromisoformat(start_time_iso)
            end_dt = start_dt + datetime.timedelta(seconds=act.duration_seconds or 0)
            end_time_iso = end_dt.isoformat()
        except:
            end_time_iso = start_time_iso

        rows_to_insert.append({
            "id": act_id,
            "habit_name": habit_name,
            "start_time": start_time_iso,
            "end_time": end_time_iso,
            "duration_second": int(act.duration_seconds or 0),
            "detail": f"Garmin: {act.activity_name} ({act.activity_type})",
        })
        synced_count += 1

    if rows_to_insert:
        errors = bq_client.insert_rows_json(table_id, rows_to_insert)
        if errors:
            return f"Error inserting into BigQuery: {errors}"
        return f"Successfully synced {synced_count} Garmin activities."
    
    return "All recent Garmin activities are already synced."
