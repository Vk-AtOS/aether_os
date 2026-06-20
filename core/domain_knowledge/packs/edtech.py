"""EdTech domain knowledge pack — FERPA, COPPA, ADA Section 508, LTI 1.3."""
from __future__ import annotations

from aether_os.core.domain_knowledge.base import (
    BusinessProcessPipeline, ComplianceRule, DomainKnowledgePack,
    EntityTemplate, FieldDef, ProcessStep, WorkflowTemplate,
)

PACK = DomainKnowledgePack(
    domain="edtech",
    display_name="EdTech / Learning Management / Online Education",

    entities=[
        EntityTemplate(
            name="Course", table="courses",
            description="Course content unit — published before students can enroll",
            fields=[
                FieldDef("course_id", "string"),
                FieldDef("instructor_id", "fk"),
                FieldDef("title", "string"),
                FieldDef("description", "text"),
                FieldDef("status", "string"),             # draft | published | archived
                FieldDef("price_cents", "int"),
                FieldDef("category", "string"),
                FieldDef("tags", "text"),
                FieldDef("max_enrollment", "int", required=False),
                FieldDef("published_at", "datetime", required=False),
            ],
            indexes=["category", "status", "instructor_id"],
            audit_trail=False,
        ),
        EntityTemplate(
            name="Enrollment", table="enrollments",
            description="Student course enrollment — FERPA protects all enrollment records",
            fields=[
                FieldDef("course_id", "fk"),
                FieldDef("student_id", "fk", pii=True),
                FieldDef("status", "string"),             # active | completed | dropped | suspended
                FieldDef("enrolled_at", "datetime"),
                FieldDef("completed_at", "datetime", required=False),
                FieldDef("progress_pct", "float"),
                FieldDef("last_accessed_at", "datetime", required=False),
                FieldDef("certificate_issued", "bool"),
            ],
            indexes=["course_id", "student_id", "status"],
            audit_trail=True,
        ),
        EntityTemplate(
            name="Assessment", table="assessments",
            description="Quiz, assignment, exam, or project within a course",
            fields=[
                FieldDef("assessment_id", "string"),
                FieldDef("course_id", "fk"),
                FieldDef("title", "string"),
                FieldDef("assessment_type", "string"),    # quiz | assignment | exam | project
                FieldDef("max_score", "float"),
                FieldDef("passing_score", "float"),
                FieldDef("time_limit_minutes", "int", required=False),
                FieldDef("attempts_allowed", "int"),
                FieldDef("status", "string"),             # draft | published | closed
                FieldDef("due_at", "datetime", required=False),
            ],
            indexes=["course_id", "status", "assessment_type"],
            audit_trail=False,
        ),
        EntityTemplate(
            name="AssessmentSubmission", table="assessment_submissions",
            description="Student submission — immutable once graded; FERPA protected",
            fields=[
                FieldDef("assessment_id", "fk"),
                FieldDef("student_id", "fk", pii=True, encrypted_at_rest=True),
                FieldDef("attempt_number", "int"),
                FieldDef("submitted_at", "datetime"),
                FieldDef("score", "float", required=False),
                FieldDef("graded_at", "datetime", required=False),
                FieldDef("grader_id", "fk", required=False),
                FieldDef("feedback", "text", encrypted_at_rest=True, required=False),
                FieldDef("status", "string"),             # submitted | grading | graded | returned
            ],
            indexes=["assessment_id", "student_id", "status"],
            audit_trail=True,
        ),
        EntityTemplate(
            name="Certificate", table="certificates",
            description="Course completion certificate — verifiable credential",
            fields=[
                FieldDef("student_id", "fk", pii=True, encrypted_at_rest=True),
                FieldDef("course_id", "fk"),
                FieldDef("issued_at", "datetime"),
                FieldDef("certificate_number", "string"),
                FieldDef("credential_url", "string"),
            ],
            indexes=["student_id", "course_id", "certificate_number"],
            audit_trail=True, soft_delete=False,
        ),
        EntityTemplate(
            name="LearningObjective", table="learning_objectives",
            description="Bloom's taxonomy learning objective for a course",
            fields=[
                FieldDef("course_id", "fk"),
                FieldDef("description", "text"),
                FieldDef("bloom_level", "string"),        # remember | understand | apply | analyze | evaluate | create
                FieldDef("order_index", "int"),
            ],
            indexes=["course_id"],
            audit_trail=False,
        ),
    ],

    workflows=[
        WorkflowTemplate(
            name="EnrollmentFlow",
            entity="Enrollment", field="status",
            states=["active", "completed", "dropped", "suspended"],
            transitions={
                "active":     ["completed", "dropped", "suspended"],
                "suspended":  ["active", "dropped"],
                "completed":  [],
                "dropped":    [],
            },
            terminal_states=["completed", "dropped"],
            description="Enrollment lifecycle — completion triggers certificate issuance",
        ),
        WorkflowTemplate(
            name="AssessmentFlow",
            entity="AssessmentSubmission", field="status",
            states=["submitted", "grading", "graded", "returned"],
            transitions={
                "submitted": ["grading"],
                "grading":   ["graded"],
                "graded":    ["returned"],
                "returned":  [],
            },
            terminal_states=["returned"],
            description="Submission grading pipeline — immutable after returned state",
        ),
    ],

    compliance=[
        ComplianceRule(
            "FERPA",
            "Student education records are protected — no disclosure without consent",
            ["Enrollment.student_id", "AssessmentSubmission.score", "Certificate.student_id"],
            "mandatory",
            "All student data endpoints require student_id to match authenticated user or admin role",
        ),
        ComplianceRule(
            "COPPA",
            "Parental consent required for users under 13",
            ["User.date_of_birth"],
            "mandatory",
            "Gate account creation on age verification; require parental consent for under-13 users",
        ),
        ComplianceRule(
            "ADA Section 508",
            "Course content must be accessible to users with disabilities",
            [],
            "mandatory",
            "P07c accessibility testing must validate all course pages against WCAG 2.1 AA",
        ),
    ],

    api_patterns=[
        "LTI 1.3 integration for institutional SSO",
        "SCORM/xAPI progress tracking",
        "Grade passback to institutional LMS",
        "Certificate PDF generation and verification",
        "Completion webhook for employer integrations",
    ],

    pipelines=[
        BusinessProcessPipeline(
            name="CourseCompletionFlow",
            trigger="state_transition",
            trigger_entity="Enrollment",
            trigger_condition="progress_pct >= 100 and status == 'active'",
            description="Mark enrollment complete, issue certificate, and notify integrations.",
            services_required=[
                "EnrollmentService", "CertificateService", "NotificationService", "WebhookService",
            ],
            integrations_required=["sendgrid"],
            steps=[
                ProcessStep(
                    name="verify_completion",
                    action_type="service_call",
                    service="EnrollmentService",
                    method="verify_all_requirements_met",
                    input_mapping={
                        "course_id": "entity.course_id",
                        "student_id": "entity.student_id",
                    },
                    on_success="mark_completed",
                    on_failure="FAIL",
                    description="Confirm all assessments passed and progress is 100%",
                ),
                ProcessStep(
                    name="mark_completed",
                    action_type="state_transition",
                    service="Enrollment",
                    method="status",
                    input_mapping={"status": "'completed'"},
                    on_success="issue_certificate",
                    on_failure="FAIL",
                    description="Transition enrollment status to completed",
                ),
                ProcessStep(
                    name="issue_certificate",
                    action_type="service_call",
                    service="CertificateService",
                    method="issue",
                    input_mapping={
                        "student_id": "entity.student_id",
                        "course_id": "entity.course_id",
                    },
                    on_success="send_completion_email",
                    on_failure="FAIL",
                    description="Generate certificate with verifiable credential URL",
                ),
                ProcessStep(
                    name="send_completion_email",
                    action_type="notification",
                    service="NotificationService",
                    method="send_course_completion",
                    input_mapping={
                        "student_id": "entity.student_id",
                        "course_id": "entity.course_id",
                        "certificate_id": "steps.issue_certificate.certificate_id",
                    },
                    on_success="fire_completion_webhook",
                    on_failure="SKIP",
                    description="Email student their certificate — non-fatal",
                ),
                ProcessStep(
                    name="fire_completion_webhook",
                    action_type="external_api",
                    service="WebhookService",
                    method="fire",
                    input_mapping={
                        "event": "'course.completed'",
                        "student_id": "entity.student_id",
                        "course_id": "entity.course_id",
                    },
                    on_success="END",
                    on_failure="SKIP",
                    retry_count=3,
                    description="Notify employer integrations via completion webhook",
                ),
            ],
        ),
    ],

    prompt_injection=(
        "This is an educational platform. FERPA requires that student records (grades, progress, "
        "assessments) are only accessible to the student themselves and authorized instructors. "
        "Never expose student data in aggregate endpoints that could identify individuals. "
        "Assessment submissions must be immutable once graded. "
        "Certificates must have verifiable credential URLs."
    ),
)
