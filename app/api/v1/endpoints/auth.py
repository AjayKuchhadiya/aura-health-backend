from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.schemas.user import User as UserSchema
from app.models.user import User as UserModel
from app.core.database import get_db
from app.api.deps import get_current_user_token

router = APIRouter(
    prefix="/auth",
    tags=["auth"],
    responses={404: {"description": "Not found"}},
)

@router.post("/sync", response_model=UserSchema)
async def sync_user(
    token_data: dict = Depends(get_current_user_token),
    db: AsyncSession = Depends(get_db)
):
    """
    Unified Auth Endpoint:
    1. Verifies the Firebase Token (via dependency).
    2. Checks if the user exists in Postgres.
    3. If NOT (Registration flow): Creates the user.
    4. If YES (Login flow): Returns the user.
    """
    firebase_uid = token_data.get("uid")
    email = token_data.get("email")
    
    # 1. Try to find the user in our database
    result = await db.execute(select(UserModel).where(UserModel.firebase_uid == firebase_uid))
    user = result.scalars().first()
    
    # 2. If user doesn't exist, create them (Registration Logic)
    if not user:
        new_user = UserModel(
            firebase_uid=firebase_uid,
            email=email,
            username=email.split("@")[0], # Default username from email
            role="patient",               # Default role
            medical_profile={}            # Initialize empty profile
        )
        db.add(new_user)
        await db.commit()
        await db.refresh(new_user)
        return new_user
    
    # 3. If user exists, just return them (Login Logic)
    return user