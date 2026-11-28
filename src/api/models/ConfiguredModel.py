import json
from types import UnionType
from typing import Any
from typing import Literal
from typing import TypedDict
from typing import get_args
from typing import get_origin

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import field_validator
from PyQt6.QtCore import QByteArray

from src.util import decapitalize


class BareJSONAPIRelationship(TypedDict):
    data: dict[Literal["id", "type"], str]


type ModelConcreteValue = str | float | bool
type ModelRelationshipValue = (
    dict[str, ModelConcreteValue | ModelRelationshipValue]
    | list[ModelRelationshipValue]
)
type PossibleFieldValue = ModelConcreteValue | ModelRelationshipValue


def api_response_empty(resp: ModelRelationshipValue) -> bool:
    return not resp or set(resp) == {"id", "type"}


class ConfiguredModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    @field_validator("*", mode="before")
    @classmethod
    def ensure_included_and_not_empty_or_none(
            cls,
            v: PossibleFieldValue,
    ) -> PossibleFieldValue | None:
        if isinstance(v, dict):
            if api_response_empty(v):
                return None
        elif isinstance(v, list):
            if not v or len(list(filter(api_response_empty, v))) == len(v):
                return None
        return v

    @classmethod
    def to_jsonapi_relationship(cls, id: str | int = "") -> BareJSONAPIRelationship:
        return {
            "data": {
                "type": decapitalize(cls.__name__),
                "id": str(id),
            },
        }

    @staticmethod
    def _relationship_target(annotation: Any) -> tuple[type[ConfiguredModel] | None, bool]:
        if get_origin(annotation) is UnionType:
            annotation = get_args(annotation)[0]
        many = get_origin(annotation) is list
        if many:
            annotation = get_args(annotation)[0]
        if isinstance(annotation, type) and issubclass(annotation, ConfiguredModel):
            return annotation, many
        return None, False

    @classmethod
    def to_jsonapi_doc(
            cls,
            _exclude_fields: set[str] = set(),
            _select_relationships: set[str] = set(),
            **values: Any,
    ) -> dict[Literal["data"], dict[str, Any]]:
        doc: dict[Literal["data"], dict[str, Any]] = {"data": {}}
        attributes = {}
        relationships: dict[str, Any] = {}
        doc["data"]["id"] = ""
        doc["data"]["type"] = decapitalize(cls.__name__)
        for name, field in cls.model_fields.items():
            if {name, field.alias} & _exclude_fields:
                continue
            field_name = field.alias or name
            if field_name == "id":
                id = values.pop("id", None)
                xd = values.pop("xd", None)
                doc["data"]["id"] = id or xd or "null"
                continue
            assert field.annotation is not None
            if field.is_required():
                value = values.pop(field_name, None)
                if value is None:
                    if isinstance(field.annotation, UnionType):  # pyright: ignore[reportUnnecessaryIsInstance]  # noqa: E501
                        value = field.annotation.__args__[0]()
                    else:
                        value = field.annotation()
                attributes[field_name] = value
                continue
            klass, many = cls._relationship_target(field.annotation)
            if klass is None:
                if field_name in values:
                    attributes[field_name] = values.pop(field_name)
            elif field_name in _select_relationships or not _select_relationships:
                relation = values.pop(field_name, {})
                if relation is None:
                    continue
                if many:
                    relationships[field_name] = {
                        "data": [klass.to_jsonapi_relationship(r["id"])["data"] for r in relation],
                    }
                else:
                    relation_id = relation.get("id")
                    assert relation_id is not None, "Relationship id can't be empty."
                    relationships[field_name] = klass.to_jsonapi_relationship(relation_id)
        doc["data"]["attributes"] = attributes
        doc["data"]["relationships"] = relationships
        return doc

    @classmethod
    def to_jsonapi_payload(
        cls,
        _exclude_fields: set[str] = set(),
        _select_relationships: set[str] = set(),
        **values: Any,
    ) -> QByteArray:
        doc = cls.to_jsonapi_doc(_exclude_fields, _select_relationships, **values)
        return QByteArray(json.dumps(doc).encode())
