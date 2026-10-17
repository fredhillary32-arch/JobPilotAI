"""Start a discovery pass from the app and follow its progress.

POST only starts a background pass (registry sources, the same runner as the
operator CLI) and returns at once; no page request waits on external sites.
Nothing about the candidate is sent to any source: adapters only read public
feeds. Requires an authenticated session and the session's CSRF token.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import sessionmaker

from app.api.v1.dependencies import require_authenticated_resource_access
from app.db import DatabaseSession
from app.services import discovery_runner
from app.services.discovery_runner import DiscoveryBusy, run_refresh_in_background
from app.services.source_registry import load_registry

router = APIRouter(
    prefix="/job-discovery",
    tags=["job discovery"],
    dependencies=[Depends(require_authenticated_resource_access)],
)


class RefreshRequest(BaseModel):
    # Registry ids; empty means every enabled source.
    sources: Annotated[list[str], Field(max_length=50)] = []
    # Read each source's whole window instead of only what is new.
    full: bool = False


@router.post("/refresh", status_code=status.HTTP_202_ACCEPTED)
def start_refresh(body: RefreshRequest, session: DatabaseSession) -> dict:
    registry = {entry.id: entry for entry in load_registry()}
    unknown = [item for item in body.sources if item not in registry]
    if unknown:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=f"Unknown source(s): {', '.join(unknown)}"
        )
    chosen = [registry[item] for item in dict.fromkeys(body.sources)] or [e for e in registry.values() if e.enabled]
    manual = [entry.id for entry in chosen if not entry.enabled]
    if manual:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Manual-only sources are never fetched: {', '.join(manual)}",
        )
    factory = sessionmaker(bind=session.get_bind(), autoflush=False, expire_on_commit=False)
    try:
        state = run_refresh_in_background(factory, chosen, full=body.full)
    except DiscoveryBusy:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="A discovery pass is already running."
        ) from None
    return state.as_dict()


@router.get("/refresh")
def read_refresh() -> dict:
    """Progress of the current or most recent pass started in this server process."""
    return discovery_runner.refresh_state.as_dict()
