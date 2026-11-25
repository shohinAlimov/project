from datetime import date
from typing import Annotated, Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator
from urllib.parse import urlsplit

Text = Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)]
Name = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=150)
]
Lang = Literal["ru", "uz"]
Money = Annotated[int, Field(gt=0, le=10**12)]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Profile(Model):
    name: Name
    language: Lang = "uz"
    business_type: Literal["bakery", "shop"] = "shop"
    description: Text = ""
    stage: Text = ""
    assortment: Text = ""
    customers: Text = ""
    goals: Text = ""
    delivery: Text = ""
    payment: Text = ""
    delivery_other: Text = ""
    payment_other: Text = ""
    payme: Text = ""
    click: Text = ""
    followup: Text = ""
    followup_extra: Text = ""
    color: str = Field(default="#286452", pattern=r"^#[a-fA-F0-9]{6}$")
    tone: Text = ""
    logo: Text = ""

    @field_validator("payme", "click")
    @classmethod
    def checkout_link(cls, value):
        if value:
            url = urlsplit(value)
            if (
                url.scheme != "https"
                or not url.hostname
                or url.username
                or url.password
            ):
                raise ValueError("Enter an HTTPS checkout URL")
        return value


class Product(Model):
    name: Name
    price: Annotated[int, Field(ge=0, le=10**12)]
    description: Text = ""
    variants: Text = ""
    availability: Text = ""
    lead_time: Text = ""
    sourcing: Text = ""
    variants_other: Text = ""
    availability_other: Text = ""
    lead_time_other: Text = ""


class Faq(Model):
    question: Name
    answer: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1800)
    ]
    language: Lang


class Order(Model):
    product_id: UUID
    customer: Name
    total: Money
    due: date | None = None


class Entry(Model):
    request_id: UUID
    kind: Literal["income", "expense"]
    amount: Money
    day: date
    category: Name
    note: Text = ""
    reference: Text = ""
    order_id: UUID | None = None
    receipt_id: UUID | None = None
    payment_type: Literal["deposit", "final"] | None = None
    verified: bool = False


class Question(Model):
    question: Name


class Pause(Model):
    paused: bool


class AccountEmail(Model):
    email: Name


class Credentials(AccountEmail):
    password: str = Field(min_length=6, max_length=200)


class Invite(Model):
    email: Name
    role: Literal["finance", "marketing"]
