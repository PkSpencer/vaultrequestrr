"""Self-service account linking: resolve a Discord user to a Seerr user."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum, auto

from .seerr import SeerrClient, SeerrError, SeerrUser
from .store import AccountLink, LinkStore

logger = logging.getLogger(__name__)


class LinkStatus(Enum):
    LINKED = auto()
    NOT_FOUND = auto()  # no Seerr user matched the provided Plex identity
    ALREADY_CREATED = auto()  # Discord user already used their 1 local account slot
    ALREADY_LINKED = auto()  # Discord user is already linked to a Seerr account
    ERROR = auto()  # Seerr could not be reached or rejected creation

@dataclass(frozen=True)
class LinkResult:
    status: LinkStatus
    user: SeerrUser | None = None
    message: str | None = None


class AccountLinker:
    def __init__(self, seerr: SeerrClient, store: LinkStore) -> None:
        self._seerr = seerr
        self._store = store

    async def get_link(self, discord_id: str) -> AccountLink | None:
        return await self._store.get(discord_id)

    async def is_linked(self, discord_id: str) -> bool:
        return await self._store.get(discord_id) is not None

    async def link(self, discord_id: str, plex_identity: str) -> LinkResult:
        """Resolve `plex_identity` to a Seerr user and persist the link.

        On success the link is saved locally and the Discord ID is also
        written back into the Seerr user's notification settings (best
        effort — a write-back failure does not fail the link).
        """
        try:
            user = await self._seerr.find_user_by_plex_identity(plex_identity)
        except SeerrError as exc:
            logger.warning("Seerr lookup failed during linking: %s", exc)
            return LinkResult(LinkStatus.ERROR, message=str(exc))

        if user is None:
            return LinkResult(LinkStatus.NOT_FOUND)

        await self._store.save(
            discord_id=discord_id,
            seerr_user_id=user.id,
            plex_username=user.plex_username,
            email=user.email,
        )

        try:
            await self._seerr.add_discord_id(user.id, discord_id)
        except SeerrError as exc:
            logger.warning(
                "Linked Discord %s -> Seerr user %s locally, but write-back failed: %s",
                discord_id,
                user.id,
                exc,
            )

        return LinkResult(LinkStatus.LINKED, user=user)

    async def unlink(self, discord_id: str) -> None:
        await self._store.remove(discord_id)
        
    async def register_local(
        self,
        discord_id: str,
        username: str,
        email: str,
        password: str,
    ) -> LinkResult:
        """Create a local Seerr user (limit 1 per Discord ID) and link it."""
        existing_created = await self._store.get_local_account(discord_id)
        if existing_created is not None:
            return LinkResult(
                LinkStatus.ALREADY_CREATED,
                message=f"You have already created a local account (`{existing_created.username}`). Limit is one per Discord user.",
            )

        existing_link = await self._store.get(discord_id)
        if existing_link is not None:
            return LinkResult(
                LinkStatus.ALREADY_LINKED,
                message="Your Discord account is already linked to a Seerr account.",
            )

        # Also check if the email or username already exists in Seerr
        try:
            existing_seerr = await self._seerr.find_user_by_plex_identity(email) or await self._seerr.find_user_by_plex_identity(username)
            if existing_seerr is not None:
                return LinkResult(
                    LinkStatus.ERROR,
                    message="A Seerr user with that username or email already exists.",
                )
            user = await self._seerr.create_local_user(
                email=email,
                username=username,
                password=password,
            )
        except SeerrError as exc:
            logger.warning("Seerr local user creation failed for Discord %s: %s", discord_id, exc)
            return LinkResult(LinkStatus.ERROR, message=str(exc))

        # Record permanent 1-per-user creation and link the account
        await self._store.record_local_account(
            discord_id=discord_id,
            seerr_user_id=user.id,
            username=user.username or username,
            email=user.email or email,
        )
        await self._store.save(
            discord_id=discord_id,
            seerr_user_id=user.id,
            plex_username=user.username or user.display_name or username,
            email=user.email or email,
        )

        try:
            await self._seerr.add_discord_id(user.id, discord_id)
        except SeerrError as exc:
            logger.warning(
                "Created local Seerr user %s for Discord %s, but Discord ID write-back failed: %s",
                user.id,
                discord_id,
                exc,
            )

        return LinkResult(LinkStatus.LINKED, user=user)
        
        async def reset_local_account(self, discord_id: str) -> None:
        """Remove the permanent local creation record so the user can register again."""
        await self._store.remove_local_account(discord_id)
