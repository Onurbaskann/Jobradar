from app.profile.processing import (
    EducationData,
    ExperienceData,
    ResumeExtraction,
    SkillData,
    calculate_ats_score,
    normalize_fact_name,
    supplement_contacts,
)


def test_complete_resume_receives_full_deterministic_score() -> None:
    extraction = ResumeExtraction(
        summary="Backend geliştirici",
        email="onur@example.com",
        phone="+90 555 000 00 00",
        linkedin_url="https://linkedin.com/in/onur",
        experiences=[
            ExperienceData(
                employer="Acme",
                title="Backend Developer",
                start_year=2022,
                end_year=2025,
                description=".NET servisleri geliştirdi",
            )
        ],
        education=[EducationData(institution="Örnek Üniversitesi")],
        skills=[SkillData(name=".NET", evidence="Acme'de .NET servisleri geliştirdi")],
    )

    score = calculate_ats_score("Okunabilir CV metni " * 80, extraction)

    assert score.overall == 100
    assert score.findings == []


def test_score_reports_missing_contact_sections_and_evidence() -> None:
    extraction = ResumeExtraction(skills=[SkillData(name="Python")])

    score = calculate_ats_score("kısa metin", extraction)

    assert score.overall < 50
    assert any("E-posta" in finding for finding in score.findings)
    assert any("kanıtıyla" in finding for finding in score.findings)


def test_fact_names_are_normalized_for_resume_local_uniqueness() -> None:
    assert normalize_fact_name("  ASP.NET   Core ") == "asp.net core"


def test_explicit_contacts_are_recovered_without_llm_guessing() -> None:
    extraction = supplement_contacts(
        "İzmir +90 531 300 8764 onur@example.com linkedin.com/in/onur github.com/onur",
        ResumeExtraction(),
    )

    assert extraction.email == "onur@example.com"
    assert extraction.phone == "+90 531 300 8764"
    assert extraction.linkedin_url == "linkedin.com/in/onur"
    assert extraction.github_url == "github.com/onur"
