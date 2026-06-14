"""API банковских данных для фронтенда."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.storage.database import Database

router = APIRouter(prefix="/api/data", tags=["data"])


class EmployeeCreate(BaseModel):
    lastName: str = ""
    firstName: str = ""
    middleName: str = ""
    position: str = ""
    account: str = ""
    phone: str = ""


class CardStatusUpdate(BaseModel):
    status: str


class StatementGenerate(BaseModel):
    user_id: str = "demo_user"
    account: str = "all"
    period: str = "today"
    zero_turnover: bool = False
    daily: bool = False
    revaluation: bool = False


def create_data_router(db: Database) -> APIRouter:
    @router.get("/profile")
    async def get_profile(user_id: str = "demo_user"):
        profile = db.get_profile(user_id)
        return {
            **profile,
            "totalBalance": db.get_total_balance_byn(user_id),
        }

    @router.get("/accounts")
    async def get_accounts(user_id: str = "demo_user"):
        return {"accounts": db.get_accounts(user_id)}

    @router.get("/employees")
    async def list_employees(user_id: str = "demo_user"):
        return {"employees": db.get_employees(user_id)}

    @router.post("/employees")
    async def create_employee(data: EmployeeCreate, user_id: str = "demo_user"):
        if not data.lastName.strip() and not data.firstName.strip():
            raise HTTPException(status_code=400, detail="Укажите имя или фамилию сотрудника")
        employee = db.create_employee(user_id, data.model_dump())
        return {"employee": employee}

    @router.delete("/employees/{employee_id}")
    async def delete_employee(employee_id: str, user_id: str = "demo_user"):
        deleted = db.delete_employee(user_id, employee_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Сотрудник не найден")
        return {"deleted": True}

    @router.get("/cards")
    async def list_cards(user_id: str = "demo_user"):
        cards = db.get_cards(user_id)
        items = [
            {
                "id": c["id"],
                "number": c["id"],
                "date": c["doc_date"],
                "status": "Заблокирована" if c["status"] == "blocked" else "Активна",
                "statusType": "draft" if c["status"] == "blocked" else "signed",
                **c,
            }
            for c in cards
        ]
        return {"cards": cards, "items": items}

    @router.get("/cards/{card_id}")
    async def get_card(card_id: str, user_id: str = "demo_user"):
        card = db.get_card(user_id, card_id)
        if not card:
            raise HTTPException(status_code=404, detail="Карта не найдена")
        return {"card": card}

    @router.patch("/cards/{card_id}/status")
    async def update_card_status(card_id: str, body: CardStatusUpdate, user_id: str = "demo_user"):
        if body.status not in ("active", "blocked"):
            raise HTTPException(status_code=400, detail="Статус должен быть active или blocked")
        card = db.update_card_status(user_id, card_id, body.status)
        if not card:
            raise HTTPException(status_code=404, detail="Карта не найдена")
        return {"card": card}

    @router.get("/statement/reference")
    async def statement_reference(user_id: str = "demo_user"):
        ref = db.get_statement_reference()
        accounts = db.get_accounts(user_id)
        account_options = [{"key": "all", "label": "Все валюты • Все счета"}]
        for a in accounts:
            account_options.append({
                "key": a["id"],
                "label": f"{a['currency']} • {a['number'][-4:]} • {a['name']}",
            })
        return {**ref, "accountOptions": account_options}

    @router.post("/statements/generate")
    async def generate_statement(body: StatementGenerate):
        result = db.generate_statement(
            body.user_id,
            account=body.account,
            period=body.period,
            zero_turnover=body.zero_turnover,
            daily=body.daily,
            revaluation=body.revaluation,
        )
        return result

    @router.get("/accounts/{account_id}/operations/reference")
    async def account_operations_reference(account_id: str, user_id: str = "demo_user"):
        accounts = db.get_accounts(user_id)
        if not any(a["id"] == account_id for a in accounts):
            raise HTTPException(status_code=404, detail="Счёт не найден")
        return db.get_account_operations_reference()

    @router.get("/accounts/{account_id}/operations")
    async def account_operations(
        account_id: str,
        user_id: str = "demo_user",
        period: str = "all",
        operation_type: str = "all",
    ):
        result = db.get_account_operations(user_id, account_id, period, operation_type)
        if result is None:
            raise HTTPException(status_code=404, detail="Счёт не найден")
        return result

    return router
