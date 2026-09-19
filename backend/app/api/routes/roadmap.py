"""Daily-management and household APIs built on the trusted financial ledger."""

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.schemas.roadmap import (
    BillCreate,
    BillResponse,
    BillUpdate,
    CardDisputeCreate,
    CardDisputeResponse,
    CardDisputeUpdate,
    HealthChecklistResponse,
    HealthChecklistUpsert,
    HouseholdCreate,
    HouseholdExpenseCreate,
    HouseholdExpenseResponse,
    HouseholdMemberCreate,
    HouseholdMemberResponse,
    HouseholdMemberUpdate,
    HouseholdSettlementCreate,
    HouseholdSettlementResponse,
    HouseholdSettlementUpdate,
    HouseholdSummary,
    PayoffComparisonResponse,
)
from app.security import get_current_user_optional, resolve_user_scope
from app.services.roadmap_service import RoadmapService

router = APIRouter(tags=["Roadmap extensions"])


def _scope(user_id: str, current_user: User | None) -> str:
    return resolve_user_scope(user_id, current_user)


def _raise_service_error(exc: Exception) -> None:
    if isinstance(exc, LookupError):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, PermissionError):
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/bills", response_model=list[BillResponse])
async def list_bills(
    user_id: str,
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    return await RoadmapService(db).list_bills(_scope(user_id, current_user))


@router.post("/bills", response_model=BillResponse, status_code=201)
async def create_bill(
    data: BillCreate,
    user_id: str,
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await RoadmapService(db).create_bill(_scope(user_id, current_user), data)
    except (LookupError, PermissionError, ValueError) as exc:
        _raise_service_error(exc)


@router.patch("/bills/{bill_id}", response_model=BillResponse)
async def update_bill(
    bill_id: str,
    data: BillUpdate,
    user_id: str,
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    result = await RoadmapService(db).update_bill(_scope(user_id, current_user), bill_id, data)
    if result is None:
        raise HTTPException(status_code=404, detail="Bill not found")
    return result


@router.get("/health-checklist", response_model=list[HealthChecklistResponse])
async def list_health_checklist(
    user_id: str,
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    return await RoadmapService(db).list_health(_scope(user_id, current_user))


@router.put(
    "/health-checklist/{item_type}",
    response_model=HealthChecklistResponse,
)
async def upsert_health_checklist(
    item_type: str,
    data: HealthChecklistUpsert,
    user_id: str,
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    if item_type != data.item_type:
        raise HTTPException(
            status_code=422,
            detail="Checklist item type must match the request path",
        )
    return await RoadmapService(db).upsert_health(_scope(user_id, current_user), data)


@router.get(
    "/cards/{account_id}/disputes",
    response_model=list[CardDisputeResponse],
)
async def list_card_disputes(
    account_id: str,
    user_id: str,
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await RoadmapService(db).list_disputes(_scope(user_id, current_user), account_id)
    except (LookupError, PermissionError, ValueError) as exc:
        _raise_service_error(exc)


@router.post(
    "/cards/{account_id}/disputes",
    response_model=CardDisputeResponse,
    status_code=201,
)
async def create_card_dispute(
    account_id: str,
    data: CardDisputeCreate,
    user_id: str,
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await RoadmapService(db).create_dispute(
            _scope(user_id, current_user), account_id, data
        )
    except (LookupError, ValueError) as exc:
        _raise_service_error(exc)


@router.patch(
    "/card-disputes/{dispute_id}",
    response_model=CardDisputeResponse,
)
async def update_card_dispute(
    dispute_id: str,
    data: CardDisputeUpdate,
    user_id: str,
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    result = await RoadmapService(db).update_dispute(
        _scope(user_id, current_user), dispute_id, data
    )
    if result is None:
        raise HTTPException(status_code=404, detail="Card dispute not found")
    return result


@router.get("/households", response_model=list[HouseholdSummary])
async def list_households(
    user_id: str,
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    return await RoadmapService(db).list_households(_scope(user_id, current_user))


@router.post("/households", response_model=HouseholdSummary, status_code=201)
async def create_household(
    data: HouseholdCreate,
    user_id: str,
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    return await RoadmapService(db).create_household(_scope(user_id, current_user), data)


@router.post(
    "/households/{household_id}/members",
    response_model=HouseholdSummary,
)
async def add_household_member(
    household_id: str,
    data: HouseholdMemberCreate,
    user_id: str,
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await RoadmapService(db).add_household_member(
            _scope(user_id, current_user), household_id, data
        )
    except (LookupError, PermissionError, ValueError) as exc:
        _raise_service_error(exc)


@router.get(
    "/households/{household_id}/members",
    response_model=list[HouseholdMemberResponse],
)
async def list_household_members(
    household_id: str,
    user_id: str,
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await RoadmapService(db).list_household_members(
            _scope(user_id, current_user), household_id
        )
    except LookupError as exc:
        _raise_service_error(exc)


@router.delete(
    "/households/{household_id}/members/{member_user_id}",
    status_code=204,
)
async def remove_household_member(
    household_id: str,
    member_user_id: str,
    user_id: str,
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    try:
        await RoadmapService(db).remove_household_member(
            _scope(user_id, current_user),
            household_id,
            member_user_id,
        )
    except (LookupError, PermissionError, ValueError) as exc:
        _raise_service_error(exc)


@router.patch(
    "/households/{household_id}/members/{member_user_id}",
    response_model=HouseholdMemberResponse,
)
async def update_household_member(
    household_id: str,
    member_user_id: str,
    data: HouseholdMemberUpdate,
    user_id: str,
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await RoadmapService(db).update_household_member(
            _scope(user_id, current_user),
            household_id,
            member_user_id,
            data,
        )
    except (LookupError, PermissionError, ValueError) as exc:
        _raise_service_error(exc)


@router.delete("/households/{household_id}", status_code=204)
async def delete_household(
    household_id: str,
    user_id: str,
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    try:
        await RoadmapService(db).delete_household(_scope(user_id, current_user), household_id)
    except (LookupError, PermissionError, ValueError) as exc:
        _raise_service_error(exc)


@router.get(
    "/households/{household_id}/expenses",
    response_model=list[HouseholdExpenseResponse],
)
async def list_household_expenses(
    household_id: str,
    user_id: str,
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await RoadmapService(db).list_household_expenses(
            _scope(user_id, current_user), household_id
        )
    except LookupError as exc:
        _raise_service_error(exc)


@router.post(
    "/households/{household_id}/expenses",
    response_model=HouseholdExpenseResponse,
    status_code=201,
)
async def create_household_expense(
    household_id: str,
    data: HouseholdExpenseCreate,
    user_id: str,
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await RoadmapService(db).create_household_expense(
            _scope(user_id, current_user), household_id, data
        )
    except (LookupError, PermissionError, ValueError) as exc:
        _raise_service_error(exc)


@router.patch(
    "/households/{household_id}/settlements/{settlement_id}",
    response_model=HouseholdSettlementResponse,
)
async def update_household_settlement(
    household_id: str,
    settlement_id: str,
    data: HouseholdSettlementUpdate,
    user_id: str,
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    try:
        result = await RoadmapService(db).update_household_settlement(
            _scope(user_id, current_user),
            household_id,
            settlement_id,
            data,
        )
    except (LookupError, PermissionError, ValueError) as exc:
        _raise_service_error(exc)
    if result is None:
        raise HTTPException(status_code=404, detail="Household settlement not found")
    return result


@router.get(
    "/households/{household_id}/settlements",
    response_model=list[HouseholdSettlementResponse],
)
async def list_household_settlements(
    household_id: str,
    user_id: str,
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await RoadmapService(db).list_household_settlements(
            _scope(user_id, current_user), household_id
        )
    except LookupError as exc:
        _raise_service_error(exc)


@router.post(
    "/households/{household_id}/settlements",
    response_model=HouseholdSettlementResponse,
    status_code=201,
)
async def create_household_settlement(
    household_id: str,
    data: HouseholdSettlementCreate,
    user_id: str,
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await RoadmapService(db).create_household_settlement(
            _scope(user_id, current_user), household_id, data
        )
    except (LookupError, PermissionError, ValueError) as exc:
        _raise_service_error(exc)


@router.get(
    "/liabilities/payoff-comparison",
    response_model=PayoffComparisonResponse,
)
async def payoff_comparison(
    user_id: str,
    monthly_budget: Decimal = Query(..., gt=0, decimal_places=2),
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    return await RoadmapService(db).payoff_comparison(_scope(user_id, current_user), monthly_budget)
