from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.infrastructure.db.models import UserModel, WorkspaceMemberModel, WorkspaceModel
from app.shared.ids import new_id
from app.shared.security import create_access_token, hash_password, verify_password


class AuthService:
    def __init__(self, db: Session, secret_key: str, token_ttl_seconds: int) -> None:
        self.db = db
        self.secret_key = secret_key
        self.token_ttl_seconds = token_ttl_seconds

    def register(self, email: str, password: str, name: str) -> dict:
        normalized_email = email.strip().lower()
        if self.db.query(UserModel).filter(UserModel.email == normalized_email).first():
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")
        user = UserModel(id=new_id(), email=normalized_email, name=name.strip(), password_hash=hash_password(password))
        workspace = WorkspaceModel(id=new_id(), name=f"{name.strip() or normalized_email}'s Workspace", owner_id=user.id)
        membership = WorkspaceMemberModel(id=new_id(), workspace_id=workspace.id, user_id=user.id, role="owner")
        self.db.add_all([user, workspace, membership])
        self.db.commit()
        return self._token_response(user)

    def login(self, email: str, password: str) -> dict:
        user = self.db.query(UserModel).filter(UserModel.email == email.strip().lower()).first()
        if user is None or not verify_password(password, user.password_hash):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")
        return self._token_response(user)

    def _token_response(self, user: UserModel) -> dict:
        token = create_access_token(user.id, self.secret_key, self.token_ttl_seconds)
        return {"access_token": token, "token_type": "bearer", "user": serialize_user(user)}


def serialize_user(user: UserModel) -> dict:
    return {"id": user.id, "email": user.email, "name": user.name, "created_at": user.created_at.isoformat()}
