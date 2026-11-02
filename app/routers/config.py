from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.config_service import Config, ConfigUpdate, get_config, update_config
from app.deps import get_db, require

router = APIRouter(prefix="/api/config", tags=["config"])


@router.get("", response_model=Config, operation_id="getConfig", dependencies=[Depends(require("config:read"))])
def read(db: Session = Depends(get_db)):
    return get_config(db)


@router.patch("", response_model=Config, operation_id="updateConfig", dependencies=[Depends(require("config:write"))])
def write(body: ConfigUpdate, db: Session = Depends(get_db)):
    return update_config(db, body)
