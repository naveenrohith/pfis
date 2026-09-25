"""Financial account, balance, net-worth, and transfer routes."""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.schemas.account import (
    AccountIdentitySnapshotResponse,
    AccountLinkRuleCreate,
    AccountLinkRuleResponse,
    BalanceCoverageResponse,
    BalanceObservationCreate,
    BalanceObservationResponse,
    BalanceProviderAccountCandidateResponse,
    BalanceProviderAccountMappingRequest,
    BalanceProviderAccountMappingResponse,
    BalanceProviderConnectionRequest,
    BalanceProviderConnectionResponse,
    BalanceProviderStatusResponse,
    BalanceSnapshotCreate,
    BalanceSnapshotResponse,
    CardPositionObservationCreate,
    CardPositionObservationResponse,
    CashPocketBalanceResponse,
    FinancialAccountCreate,
    FinancialAccountResponse,
    FinancialAccountUpdate,
    NetWorthSeries,
    TransferCreate,
    TransferResponse,
)
from app.security import get_current_user_optional, resolve_user_scope
from app.services.account_service import AccountService
from app.services.balance_observation_service import (
    BalanceObservationService,
    observation_from_create,
)
from app.services.balance_provider_connection_service import BalanceProviderConnectionService
from app.services.balance_provider_discovery_service import BalanceProviderDiscoveryService
from app.services.balance_provider_mapping_service import BalanceProviderMappingService
from app.services.balance_provider_status_service import BalanceProviderStatusService
from app.services.card_position_observation_service import (
    CardPositionObservationService,
)
from app.services.card_position_observation_service import (
    observation_from_create as card_observation_from_create,
)

router = APIRouter(tags=["Accounts"])


@router.get("/account-link-rules", response_model=list[AccountLinkRuleResponse])
async def list_account_link_rules(
    user_id: str,
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    return await AccountService(db).list_link_rules(resolve_user_scope(user_id, current_user))


@router.post(
    "/account-link-rules",
    response_model=AccountLinkRuleResponse,
    status_code=201,
)
async def create_account_link_rule(
    data: AccountLinkRuleCreate,
    user_id: str,
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await AccountService(db).create_link_rule(
            resolve_user_scope(user_id, current_user), data
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete("/account-link-rules/{rule_id}", status_code=204)
async def deactivate_account_link_rule(
    rule_id: str,
    user_id: str,
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    removed = await AccountService(db).deactivate_link_rule(
        resolve_user_scope(user_id, current_user), rule_id
    )
    if not removed:
        raise HTTPException(status_code=404, detail="Account-link rule not found")


@router.get("/accounts", response_model=list[FinancialAccountResponse])
async def list_accounts(
    user_id: str,
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    user_id = resolve_user_scope(user_id, current_user)
    return await AccountService(db).list_accounts(user_id)


@router.post("/accounts", response_model=FinancialAccountResponse, status_code=201)
async def create_account(
    data: FinancialAccountCreate,
    user_id: str,
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    user_id = resolve_user_scope(user_id, current_user)
    try:
        return await AccountService(db).create_account(user_id, data)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.patch("/accounts/{account_id}", response_model=FinancialAccountResponse)
async def update_account(
    account_id: str,
    data: FinancialAccountUpdate,
    user_id: str,
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    user_id = resolve_user_scope(user_id, current_user)
    try:
        account = await AccountService(db).update_account(user_id, account_id, data)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if account is None:
        raise HTTPException(status_code=404, detail="Account not found")
    return account


@router.get(
    "/accounts/{account_id}/identity-history",
    response_model=list[AccountIdentitySnapshotResponse],
)
async def get_account_identity_history(
    account_id: str,
    user_id: str,
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    user_id = resolve_user_scope(user_id, current_user)
    history = await AccountService(db).identity_history(user_id, account_id)
    if history is None:
        raise HTTPException(status_code=404, detail="Account not found")
    return history


@router.get(
    "/accounts/{account_id}/cash-pocket",
    response_model=CashPocketBalanceResponse,
)
async def get_cash_pocket_balance(
    account_id: str,
    user_id: str,
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    user_id = resolve_user_scope(user_id, current_user)
    try:
        balance = await AccountService(db).cash_pocket_balance(user_id, account_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if balance is None:
        raise HTTPException(status_code=404, detail="Account not found")
    return balance


@router.post(
    "/accounts/{account_id}/balances",
    response_model=BalanceSnapshotResponse,
    status_code=201,
)
async def add_account_balance(
    account_id: str,
    data: BalanceSnapshotCreate,
    user_id: str,
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    user_id = resolve_user_scope(user_id, current_user)
    try:
        balance = await AccountService(db).add_balance(user_id, account_id, data)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if balance is None:
        raise HTTPException(status_code=404, detail="Account not found")
    return balance


@router.post(
    "/accounts/{account_id}/balance-observations",
    response_model=BalanceObservationResponse,
    status_code=201,
)
async def ingest_balance_observation(
    account_id: str,
    data: BalanceObservationCreate,
    user_id: str,
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    """Ingest one provider observation with coverage and cadence evidence."""

    user_id = resolve_user_scope(user_id, current_user)
    try:
        return await BalanceObservationService(db).ingest(
            user_id,
            observation_from_create(account_id, data),
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get(
    "/accounts/{account_id}/balance-coverage",
    response_model=list[BalanceCoverageResponse],
)
async def list_balance_coverage(
    account_id: str,
    user_id: str,
    source: str | None = Query(None, max_length=24),
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    """Return source freshness/cadence evidence without exposing credentials."""

    user_id = resolve_user_scope(user_id, current_user)
    coverage = await BalanceObservationService(db).list_coverage(
        user_id,
        account_id,
        source=source,
    )
    if coverage is None:
        raise HTTPException(status_code=404, detail="Account not found")
    return coverage


@router.post(
    "/accounts/{account_id}/card-observations",
    response_model=CardPositionObservationResponse,
    status_code=201,
)
async def ingest_card_position_observation(
    account_id: str,
    data: CardPositionObservationCreate,
    user_id: str,
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    """Persist one issuer card fact and update its outstanding position."""

    user_id = resolve_user_scope(user_id, current_user)
    try:
        return await CardPositionObservationService(db).ingest(
            user_id,
            card_observation_from_create(account_id, data),
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get(
    "/accounts/{account_id}/card-observations",
    response_model=list[CardPositionObservationResponse],
)
async def list_card_position_observations(
    account_id: str,
    user_id: str,
    limit: int = Query(20, ge=1, le=100),
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    user_id = resolve_user_scope(user_id, current_user)
    observations = await CardPositionObservationService(db).list_recent(
        user_id,
        account_id,
        limit=limit,
    )
    if observations is None:
        raise HTTPException(status_code=404, detail="Account not found")
    return observations


@router.get("/balance-provider/status", response_model=BalanceProviderStatusResponse)
async def balance_provider_status(
    user_id: str,
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    """Return provider mapping/freshness readiness without exposing credentials."""

    return await BalanceProviderStatusService(db).status(resolve_user_scope(user_id, current_user))


@router.get(
    "/balance-provider/connections",
    response_model=list[BalanceProviderConnectionResponse],
)
async def list_balance_provider_connections(
    user_id: str,
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    return await BalanceProviderConnectionService(db).list_connections(
        resolve_user_scope(user_id, current_user)
    )


@router.post(
    "/balance-provider/connections",
    response_model=BalanceProviderConnectionResponse,
    status_code=202,
)
async def request_balance_provider_consent(
    data: BalanceProviderConnectionRequest,
    user_id: str,
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await BalanceProviderConnectionService(db).request_consent(
            resolve_user_scope(user_id, current_user),
            data.provider_type,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.delete(
    "/balance-provider/connections/{provider_type}",
    response_model=BalanceProviderConnectionResponse,
)
async def revoke_balance_provider_consent(
    provider_type: str,
    user_id: str,
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    connection = await BalanceProviderConnectionService(db).revoke(
        resolve_user_scope(user_id, current_user),
        provider_type,
    )
    if connection is None:
        raise HTTPException(status_code=404, detail="Balance provider connection not found")
    return connection


@router.get(
    "/balance-provider/mappings",
    response_model=list[BalanceProviderAccountMappingResponse],
)
async def list_balance_provider_mappings(
    user_id: str,
    provider_type: str | None = Query(None, max_length=50),
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    return await BalanceProviderMappingService(db).list_mappings(
        resolve_user_scope(user_id, current_user),
        provider_type,
    )


@router.get(
    "/balance-provider/discovered-accounts",
    response_model=list[BalanceProviderAccountCandidateResponse],
)
async def discover_balance_provider_accounts(
    provider_type: str = Query(..., min_length=1, max_length=50),
    user_id: str = Query(...),
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await BalanceProviderDiscoveryService(db).discover(
            resolve_user_scope(user_id, current_user),
            provider_type,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post(
    "/accounts/{account_id}/balance-provider-mapping",
    response_model=BalanceProviderAccountMappingResponse,
    status_code=201,
)
async def map_balance_provider_account(
    account_id: str,
    data: BalanceProviderAccountMappingRequest,
    user_id: str,
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await BalanceProviderMappingService(db).map_account(
            resolve_user_scope(user_id, current_user),
            account_id,
            data.provider_type,
            data.provider_account_id,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.delete(
    "/accounts/{account_id}/balance-provider-mapping/{provider_type}",
    status_code=204,
)
async def unmap_balance_provider_account(
    account_id: str,
    provider_type: str,
    user_id: str,
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    removed = await BalanceProviderMappingService(db).unmap_account(
        resolve_user_scope(user_id, current_user),
        account_id,
        provider_type,
    )
    if not removed:
        raise HTTPException(status_code=404, detail="Balance provider mapping not found")


@router.get("/net-worth", response_model=NetWorthSeries)
async def get_net_worth(
    user_id: str,
    as_of: date | None = Query(None),
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    user_id = resolve_user_scope(user_id, current_user)
    try:
        return await AccountService(db).net_worth(user_id, as_of)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/transfers", response_model=TransferResponse, status_code=201)
async def create_transfer(
    data: TransferCreate,
    user_id: str,
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    user_id = resolve_user_scope(user_id, current_user)
    try:
        return await AccountService(db).create_transfer(user_id, data)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
