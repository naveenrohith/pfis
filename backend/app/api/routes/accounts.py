"""Financial account, balance, net-worth, and transfer routes."""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.schemas.account import (
    BalanceSnapshotCreate,
    BalanceSnapshotResponse,
    FinancialAccountCreate,
    FinancialAccountResponse,
    FinancialAccountUpdate,
    NetWorthSeries,
    TransferCreate,
    TransferResponse,
)
from app.security import get_current_user_optional, resolve_user_scope
from app.services.account_service import AccountService

router = APIRouter(tags=["Accounts"])


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
    account = await AccountService(db).update_account(user_id, account_id, data)
    if account is None:
        raise HTTPException(status_code=404, detail="Account not found")
    return account


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


@router.get("/net-worth", response_model=NetWorthSeries)
async def get_net_worth(
    user_id: str,
    as_of: date | None = Query(None),
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    user_id = resolve_user_scope(user_id, current_user)
    return await AccountService(db).net_worth(user_id, as_of)


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
