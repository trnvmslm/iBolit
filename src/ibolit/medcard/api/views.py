"""MedCard (patient-only): overview, timeline, sections, documents, offline sync."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from django.http import HttpResponse
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from ibolit.core.pagination import paginate, parse_limit
from ibolit.core.policy import IsPatient, get_scoped_or_404
from ibolit.core.problems import ValidationFailed
from ibolit.core.serializers import StrictSerializer
from ibolit.files import services as files
from ibolit.medcard import presenters as p
from ibolit.medcard import selectors, services
from ibolit.medcard.models import Allergy, Condition, HealthProfile, MedicalDocument, Medication

TAG = ["MedCard"]
SINCE = OpenApiParameter("updated_since", str, description="ISO-8601; only records changed after this time")


def _parse_ts(raw: str, field: str) -> dt.datetime:
    try:
        return dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        raise ValidationFailed([{"field": field, "message": "ISO-8601 timestamp expected.", "code": "invalid"}]) from None


def _since(request: Request, qs: Any) -> Any:
    raw = request.query_params.get("updated_since")
    return qs.filter(updated_at__gt=_parse_ts(raw, "updated_since")) if raw else qs


class OverviewView(APIView):
    permission_classes = [IsPatient]

    @extend_schema(tags=TAG, summary="MedCard overview (blood type, allergies, medications, diagnoses, labs, vaccines, documents)", responses={200: OpenApiTypes.OBJECT})
    def get(self, request: Request) -> Response:
        data = selectors.overview(request.user)
        data["sharing_note"] = "Share only what matters."
        return Response(data)


class TimelineView(APIView):
    permission_classes = [IsPatient]

    @extend_schema(
        tags=TAG, summary="Medical history timeline (All / Visits / Labs / Vaccines)",
        parameters=[OpenApiParameter("kind", str, enum=list(selectors.TIMELINE_FILTERS)), OpenApiParameter("cursor", str), OpenApiParameter("limit", int)],
        responses={200: OpenApiTypes.OBJECT},
    )
    def get(self, request: Request) -> Response:
        kind_key = request.query_params.get("kind", "all")
        if kind_key not in selectors.TIMELINE_FILTERS:
            raise ValidationFailed([{"field": "kind", "message": "all, visits, labs or vaccines", "code": "invalid"}])
        qs = selectors.timeline(request.user, selectors.TIMELINE_FILTERS[kind_key])
        rows, cursor = paginate(qs, ordering=["-occurred_at", "-id"], cursor=request.query_params.get("cursor"), limit=parse_limit(request.query_params.get("limit")))
        return Response({"items": [p.timeline_entry(r) for r in rows], "next_cursor": cursor})


class HealthProfileIn(StrictSerializer):
    blood_type = serializers.ChoiceField(choices=HealthProfile.BloodType.choices, required=False)
    chronic_conditions_state = serializers.ChoiceField(choices=HealthProfile.ChronicState.choices, required=False)


class HealthProfileView(APIView):
    permission_classes = [IsPatient]

    @extend_schema(tags=TAG, summary="Blood type and chronic-conditions answer", request=HealthProfileIn, responses={200: OpenApiTypes.OBJECT})
    def patch(self, request: Request) -> Response:
        data = HealthProfileIn(data=request.data)
        data.is_valid(raise_exception=True)
        profile = services.update_health_profile(request.user, **data.validated_data)
        return Response({"blood_type": p.blood_type(profile), "chronic_conditions_state": profile.chronic_conditions_state})


class AllergyIn(StrictSerializer):
    substance = serializers.CharField(max_length=120)
    severity = serializers.ChoiceField(choices=Allergy.Severity.choices, default="unknown")
    reaction = serializers.CharField(max_length=300, required=False, allow_blank=True, allow_null=True)


class ConditionIn(StrictSerializer):
    name = serializers.CharField(max_length=200)
    status = serializers.ChoiceField(choices=Condition.Status.choices, default="active")
    noted_on = serializers.DateField(required=False, allow_null=True)


class MedicationIn(StrictSerializer):
    name = serializers.CharField(max_length=120)
    strength = serializers.CharField(max_length=60, required=False, allow_blank=True, allow_null=True)
    schedule = serializers.CharField(max_length=120, required=False, allow_blank=True, allow_null=True)
    instructions = serializers.CharField(max_length=300, required=False, allow_blank=True, allow_null=True)
    start_on = serializers.DateField(required=False, allow_null=True)
    end_on = serializers.DateField(required=False, allow_null=True)
    review_on = serializers.DateField(required=False, allow_null=True)
    is_active = serializers.BooleanField(required=False, default=True)


def _section(model: Any, serializer: type[StrictSerializer], present: Any, list_fn: Any, summary: str) -> tuple[type[APIView], type[APIView]]:
    class ListCreate(APIView):
        permission_classes = [IsPatient]

        @extend_schema(tags=TAG, summary=f"{summary}: list", parameters=[SINCE], responses={200: OpenApiTypes.OBJECT})
        def get(self, request: Request) -> Response:
            return Response({"items": [present(r) for r in _since(request, list_fn(request.user))]})

        @extend_schema(tags=TAG, summary=f"{summary}: add (patient-reported)", request=serializer, responses={201: OpenApiTypes.OBJECT})
        def post(self, request: Request) -> Response:
            data = serializer(data=request.data)
            data.is_valid(raise_exception=True)
            return Response(present(services.create_patient_record(request.user, model, data.validated_data)), status=201)

    class Detail(APIView):
        permission_classes = [IsPatient]

        @extend_schema(tags=TAG, summary=f"{summary}: edit (patient-reported only)", request=serializer, responses={200: OpenApiTypes.OBJECT})
        def patch(self, request: Request, record_id: uuid.UUID) -> Response:
            data = serializer(data=request.data, partial=True)
            data.is_valid(raise_exception=True)
            return Response(present(services.update_patient_record(request.user, model, record_id, data.validated_data)))

        @extend_schema(tags=TAG, summary=f"{summary}: delete (patient-reported only)", responses={204: None})
        def delete(self, request: Request, record_id: uuid.UUID) -> Response:
            services.delete_patient_record(request.user, model, record_id)
            return Response(status=204)

    ListCreate.__name__ = f"{model.__name__}ListCreateView"
    Detail.__name__ = f"{model.__name__}DetailView"
    return ListCreate, Detail


AllergyListView, AllergyDetailView = _section(Allergy, AllergyIn, p.allergy, selectors.allergies, "Allergies")
ConditionListView, ConditionDetailView = _section(
    Condition, ConditionIn, p.condition, lambda u: selectors.conditions(u, Condition.Kind.CHRONIC), "Chronic conditions"
)
MedicationListView, MedicationDetailView = _section(Medication, MedicationIn, p.medication, selectors.medications, "Current medications")


class DiagnosesView(APIView):
    permission_classes = [IsPatient]

    @extend_schema(tags=TAG, summary="Diagnoses (clinician-authored, read-only)", parameters=[SINCE], responses={200: OpenApiTypes.OBJECT})
    def get(self, request: Request) -> Response:
        return Response({"items": [p.condition(c) for c in _since(request, selectors.conditions(request.user, Condition.Kind.DIAGNOSIS))]})


class LabResultsView(APIView):
    permission_classes = [IsPatient]

    @extend_schema(tags=TAG, summary="Lab results", parameters=[SINCE], responses={200: OpenApiTypes.OBJECT})
    def get(self, request: Request) -> Response:
        return Response({"items": [p.lab_result(r, with_values=False) for r in _since(request, selectors.lab_results(request.user))]})


class LabResultDetailView(APIView):
    permission_classes = [IsPatient]

    @extend_schema(tags=TAG, summary="Lab result with values and reference ranges", responses={200: OpenApiTypes.OBJECT})
    def get(self, request: Request, record_id: uuid.UUID) -> Response:
        return Response(p.lab_result(get_scoped_or_404(selectors.lab_results(request.user), pk=record_id), with_values=True))


class VaccinationsView(APIView):
    permission_classes = [IsPatient]

    @extend_schema(tags=TAG, summary="Vaccinations (with next due date)", parameters=[SINCE], responses={200: OpenApiTypes.OBJECT})
    def get(self, request: Request) -> Response:
        return Response({"items": [p.vaccination(v) for v in _since(request, selectors.vaccinations(request.user))]})


class DocumentIn(StrictSerializer):
    file_id = serializers.UUIDField()
    title = serializers.CharField(max_length=200)
    kind = serializers.ChoiceField(choices=MedicalDocument.Kind.choices, default="other")
    document_date = serializers.DateField(required=False, allow_null=True)


class DocumentListView(APIView):
    permission_classes = [IsPatient]

    @extend_schema(tags=TAG, summary="Medical documents ('3 secure files · PDF and images')", parameters=[SINCE], responses={200: OpenApiTypes.OBJECT})
    def get(self, request: Request) -> Response:
        rows = list(_since(request, selectors.documents(request.user)))
        return Response({"items": [p.document(d) for d in rows], "display": p.documents_display(rows)})

    @extend_schema(tags=TAG, summary="Add an uploaded file to the MedCard", request=DocumentIn, responses={201: OpenApiTypes.OBJECT})
    def post(self, request: Request) -> Response:
        data = DocumentIn(data=request.data)
        data.is_valid(raise_exception=True)
        return Response(p.document(services.add_document(request.user, **data.validated_data)), status=201)


class DocumentDetailView(APIView):
    permission_classes = [IsPatient]

    @extend_schema(tags=TAG, summary="Download a document", responses={(200, "application/octet-stream"): OpenApiTypes.BINARY})
    def get(self, request: Request, record_id: uuid.UUID) -> Response:
        doc = get_scoped_or_404(selectors.documents(request.user), pk=record_id)
        return files.file_response(doc.file)

    @extend_schema(tags=TAG, summary="Delete a patient-uploaded document", responses={204: None})
    def delete(self, request: Request, record_id: uuid.UUID) -> Response:
        services.delete_document(request.user, record_id)
        return Response(status=204)


class SyncView(APIView):
    permission_classes = [IsPatient]

    @extend_schema(
        tags=TAG, summary="Offline sync: changes and tombstones since a server timestamp",
        parameters=[OpenApiParameter("since", str, description="server_time from the previous sync (ISO-8601)")],
        responses={200: OpenApiTypes.OBJECT},
    )
    def get(self, request: Request) -> Response:
        raw = request.query_params.get("since")
        return Response(selectors.sync(request.user, _parse_ts(raw, "since") if raw else None))


class ExportPdfView(APIView):
    permission_classes = [IsPatient]

    @extend_schema(tags=TAG, summary="Download the whole MedCard as a PDF", responses={(200, "application/pdf"): OpenApiTypes.BINARY})
    def get(self, request: Request) -> HttpResponse:
        user = request.user
        profile = services.health_profile(user)
        lines = [f"Patient: {user.full_name}", f"Date of birth: {user.date_of_birth or '-'}", f"Blood type: {profile.blood_type}", "", "Allergies:"]
        lines += [f"  - {a.substance} ({a.severity})" for a in selectors.allergies(user)] or ["  none reported"]
        lines += ["", "Current medications:"]
        lines += [f"  - {m.name} {m.strength or ''} {m.schedule or ''}".rstrip() for m in selectors.medications(user, active_only=True)] or ["  none"]
        lines += ["", "Diagnoses:"]
        lines += [f"  - {c.name} ({c.get_status_display()})" for c in selectors.conditions(user, Condition.Kind.DIAGNOSIS)] or ["  none"]
        lines += ["", "Lab results:"]
        lines += [f"  - {r.panel_name} · {r.collected_at:%d %b %Y}" for r in selectors.lab_results(user)] or ["  none"]
        lines += ["", "Vaccinations:"]
        lines += [f"  - {v.vaccine_name} · {v.administered_on:%d %b %Y}" + (f" (next due {v.next_due_on:%d %b %Y})" if v.next_due_on else "")
                  for v in selectors.vaccinations(user)] or ["  none"]
        response = HttpResponse(files.simple_pdf("iBolit MedCard", lines), content_type="application/pdf")
        response["Content-Disposition"] = 'attachment; filename="medcard.pdf"'
        return response
