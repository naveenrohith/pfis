"""AI-ready explanation routes.

These endpoints provide deterministic explanation scaffolding for embedded AI
surfaces. They intentionally operate on titles, descriptions, and aggregate
metrics supplied by the frontend, and never require raw email bodies or secrets.
"""

from fastapi import APIRouter

from app.schemas.intelligence import ExplainRequest, ExplainResponse

router = APIRouter(prefix="/ai", tags=["AI"])


@router.post("/explain", response_model=ExplainResponse)
async def explain_surface(data: ExplainRequest):
    """Return a concise deterministic explanation for a dashboard surface."""
    drivers: list[str] = []
    next_actions: list[str] = []
    metrics = data.metrics or {}

    if data.description:
        drivers.append(data.description)

    for key, value in metrics.items():
        if value is None or value == "":
            continue
        label = str(key).replace("_", " ")
        drivers.append(f"{label}: {value}")

    surface = data.surface.lower()
    if "budget" in surface:
        next_actions.extend(["Review the category transactions.", "Adjust the monthly limit if the spend is expected."])
    elif "merchant" in surface:
        next_actions.extend(["Open the latest transactions.", "Set a default category if this merchant repeats."])
    elif "category" in surface:
        next_actions.extend(["Compare the category against last month.", "Check the top merchants driving the total."])
    elif "health" in surface or "cash" in surface:
        next_actions.extend(["Review projected month-end net.", "Create a goal for the weakest signal."])
    else:
        next_actions.extend(["Open the related workspace section.", "Review any unconfirmed transactions first."])

    return ExplainResponse(
        surface=data.surface,
        summary=f"{data.title} is based on deterministic PFIS aggregates for the selected workspace.",
        drivers=drivers[:6],
        next_actions=next_actions[:4],
        safety_note="Uses aggregate dashboard context only; raw email bodies, tokens, and secrets are not included.",
    )
