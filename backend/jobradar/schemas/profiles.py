"""Schémas des profils de recherche (validation stricte des entrées)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from ..services.enrich import CONTRACT_VALUES, EXPERIENCE_LEVELS
from ..services.scoring import DEFAULT_WEIGHTS

WORK_MODES = ("onsite", "hybrid", "remote")


def _clean_list(values: list[str] | None, *, upper: bool = False, max_items: int = 60, max_len: int = 120) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for v in values or []:
        t = " ".join(str(v).split())
        if not t:
            continue
        t = t[:max_len]
        key = t.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(t.upper() if upper else t)
    if len(out) > max_items:
        raise ValueError(f"trop d'éléments (maximum {max_items})")
    return out


def _check_choices(values: list[str], allowed: tuple[str, ...], label: str) -> list[str]:
    bad = [v for v in values if v not in allowed]
    if bad:
        raise ValueError(f"{label} invalide(s) : {', '.join(bad)} (autorisés : {', '.join(allowed)})")
    return values


class ProfileBase(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    countries: list[str] = Field(default_factory=lambda: ["SN"])
    cities: list[str] = Field(default_factory=list)
    positive_keywords: list[str] = Field(default_factory=list)
    keyword_groups: dict[str, list[str]] = Field(default_factory=dict)
    excluded_keywords: list[str] = Field(default_factory=list)
    target_roles: list[str] = Field(default_factory=list)
    sectors: list[str] = Field(default_factory=list)
    contract_types: list[str] = Field(default_factory=list)
    work_modes: list[str] = Field(default_factory=list)
    experience_levels: list[str] = Field(default_factory=list)
    weights: dict[str, float] | None = None
    is_active: bool = True

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = " ".join(v.split())
        if not v:
            raise ValueError("le nom est obligatoire")
        return v

    @field_validator("countries")
    @classmethod
    def _countries(cls, v: list[str]) -> list[str]:
        raw = [" ".join(str(c).split()) for c in v]  # validé AVANT nettoyage : « SEN » ne doit pas être tronqué en « SE »
        if any(c and (len(c) != 2 or not c.isalpha()) for c in raw):
            raise ValueError("codes pays ISO à 2 lettres attendus (ex. SN)")
        return _clean_list(raw, upper=True, max_items=30, max_len=2)

    @field_validator("cities", "positive_keywords", "excluded_keywords", "target_roles", "sectors")
    @classmethod
    def _lists(cls, v: list[str]) -> list[str]:
        return _clean_list(v)

    @field_validator("keyword_groups")
    @classmethod
    def _groups(cls, v: dict[str, list[str]]) -> dict[str, list[str]]:
        if len(v) > 20:
            raise ValueError("trop de groupes (maximum 20)")
        out: dict[str, list[str]] = {}
        for name, items in v.items():
            clean_name = " ".join(str(name).split())[:80]
            cleaned = _clean_list(items)
            if clean_name and cleaned:
                out[clean_name] = cleaned
        return out

    @field_validator("contract_types")
    @classmethod
    def _contracts(cls, v: list[str]) -> list[str]:
        return _check_choices(_clean_list(v), CONTRACT_VALUES, "type(s) de contrat")

    @field_validator("work_modes")
    @classmethod
    def _modes(cls, v: list[str]) -> list[str]:
        return _check_choices(_clean_list(v), WORK_MODES, "mode(s) de travail")

    @field_validator("experience_levels")
    @classmethod
    def _levels(cls, v: list[str]) -> list[str]:
        return _check_choices(_clean_list(v), EXPERIENCE_LEVELS, "niveau(x) d'expérience")

    @field_validator("weights")
    @classmethod
    def _weights(cls, v: dict[str, float] | None) -> dict[str, float] | None:
        if v is None:
            return None
        bad = [k for k in v if k not in DEFAULT_WEIGHTS]
        if bad:
            raise ValueError(f"pondération(s) inconnue(s) : {', '.join(bad)} (autorisées : {', '.join(DEFAULT_WEIGHTS)})")
        if any(not (0 <= float(x) <= 100) for x in v.values()):
            raise ValueError("une pondération doit être comprise entre 0 et 100")
        return {k: float(x) for k, x in v.items()}


class ProfileCreate(ProfileBase):
    pass


class ProfileUpdate(BaseModel):
    """PATCH : seuls les champs envoyés sont modifiés ; ils sont validés avec les règles de ProfileBase."""

    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = None
    countries: list[str] | None = None
    cities: list[str] | None = None
    positive_keywords: list[str] | None = None
    keyword_groups: dict[str, list[str]] | None = None
    excluded_keywords: list[str] | None = None
    target_roles: list[str] | None = None
    sectors: list[str] | None = None
    contract_types: list[str] | None = None
    work_modes: list[str] | None = None
    experience_levels: list[str] | None = None
    weights: dict[str, float] | None = None
    is_active: bool | None = None

    def validated(self) -> dict[str, Any]:
        sent = self.model_dump(exclude_unset=True)
        non_null = {k: v for k, v in sent.items() if v is not None}
        try:
            checked = ProfileBase(**{"name": non_null.get("name", "x"), **non_null})
        except ValidationError as e:
            raise ValueError("; ".join(f"{'.'.join(str(x) for x in err['loc'])} : {err['msg'].removeprefix('Value error, ')}" for err in e.errors())) from e
        out: dict[str, Any] = {k: getattr(checked, k) for k in non_null}
        for k, v in sent.items():
            if v is None and k in {"weights", "description"}:
                out[k] = None  # remise à zéro explicite
        return out


class ProfileOut(ProfileBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime
    effective_weights: dict[str, float] = Field(default_factory=dict)
