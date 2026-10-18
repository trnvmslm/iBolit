"""factory_boy factories shared by the test-suite."""

from __future__ import annotations

from typing import Any

import factory

from ibolit.accounts.models import User

_phone_seq = iter(range(1_000_000, 9_999_999))


def next_phone() -> str:
    return f"+7701{next(_phone_seq)}"


class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = User
        skip_postgeneration_save = True

    phone = factory.LazyFunction(next_phone)
    role = "patient"
    full_name = factory.Faker("name")
    language = "en"

    @factory.post_generation
    def password(obj: User, create: bool, extracted: Any, **kwargs: Any) -> None:  # noqa: N805
        obj.set_password(extracted or "Correct-Horse-42")
        if create:
            obj.save(update_fields=["password"])
