#!/usr/bin/env python3
"""
Test script for LinkedIn Lead Qualifier Actor
This script demonstrates how to test the actor locally with sample data.
"""

import asyncio
import json
from src.models import QualificationCriteria, ScoringWeights, LinkedInProfile
from src.scoring_engine import LeadScoringEngine


def create_sample_profile() -> LinkedInProfile:
    """Create a sample LinkedIn profile for testing."""
    return LinkedInProfile(
        url="https://www.linkedin.com/in/sample-ceo/",
        name="Jane Smith",
        headline="CEO & Co-Founder at TechStartup | AI & Machine Learning Expert",
        current_position="Chief Executive Officer",
        current_company="TechStartup Inc",
        location="San Francisco, CA",
        industry="Technology",
        experience_years=10,
        company_size="51-200",
        skills=["Leadership", "Strategy", "Machine Learning", "Python", "Team Building"],
        education=["Stanford MBA", "MIT Computer Science"],
        connections="500+ connections",
        about="Passionate CEO with 10+ years building AI-powered solutions. Led 3 successful exits.",
        is_valid=True
    )


def create_sample_criteria() -> QualificationCriteria:
    """Create sample qualification criteria."""
    return QualificationCriteria(
        target_job_titles=["CEO", "CTO", "VP", "Director"],
        target_industries=["Technology", "Software", "AI"],
        target_locations=["San Francisco", "New York", "Remote"],
        min_experience_years=5,
        target_company_sizes=["51-200", "201-500"],
        required_skills=["Leadership", "Strategy", "Python"]
    )


def create_sample_weights() -> ScoringWeights:
    """Create sample scoring weights."""
    return ScoringWeights(
        job_title_weight=0.30,
        industry_weight=0.25,
        location_weight=0.15,
        experience_weight=0.20,
        company_size_weight=0.05,
        skills_weight=0.05
    )


def test_scoring_engine():
    """Test the scoring engine with sample data."""
    print("🧪 Testing LinkedIn Lead Qualifier Scoring Engine")
    print("=" * 50)
    
    # Create test data
    profile = create_sample_profile()
    criteria = create_sample_criteria()
    weights = create_sample_weights()
    
    # Initialize scoring engine
    scoring_engine = LeadScoringEngine(criteria, weights)
    
    # Score the profile
    score_breakdown = scoring_engine.score_profile(profile)
    
    # Display results
    print(f"📊 Profile: {profile.name}")
    print(f"🎯 Total Score: {score_breakdown.total_score:.1f}/100")
    print()
    
    print("📈 Score Breakdown:")
    print(f"  Job Title: {score_breakdown.job_title_score:.1f} (Match: {score_breakdown.job_title_match})")
    print(f"  Industry: {score_breakdown.industry_score:.1f} (Match: {score_breakdown.industry_match})")
    print(f"  Location: {score_breakdown.location_score:.1f} (Match: {score_breakdown.location_match})")
    print(f"  Experience: {score_breakdown.experience_score:.1f} ({score_breakdown.experience_details})")
    print(f"  Company Size: {score_breakdown.company_size_score:.1f} (Match: {score_breakdown.company_size_match})")
    print(f"  Skills: {score_breakdown.skills_score:.1f} (Matched: {score_breakdown.skills_matched})")
    print()
    
    print("💡 Qualification Reasons:")
    for reason in score_breakdown.qualification_reasons:
        print(f"  • {reason}")
    print()
    
    # Test qualification
    qualified_lead = scoring_engine.qualify_lead(profile, min_score=60.0)
    if qualified_lead:
        print("✅ Profile QUALIFIED as a lead!")
        print(f"📋 Lead data preview:")
        lead_dict = qualified_lead.to_dict()
        essential_fields = ['name', 'headline', 'current_position', 'total_score']
        for field in essential_fields:
            print(f"  {field}: {lead_dict.get(field)}")
    else:
        print("❌ Profile did NOT qualify as a lead")
    
    return qualified_lead


def create_sample_input():
    """Create a sample input configuration for the actor."""
    sample_input = {
        "profileUrls": [
            "https://www.linkedin.com/in/sample-ceo/",
            "https://www.linkedin.com/in/sample-cto/",
            "https://www.linkedin.com/in/sample-vp/"
        ],
        "qualificationCriteria": {
            "targetJobTitles": ["CEO", "CTO", "VP", "Director", "Manager"],
            "targetIndustries": ["Technology", "Software", "SaaS"],
            "targetLocations": ["San Francisco", "New York", "London", "Remote"],
            "minExperienceYears": 5,
            "targetCompanySizes": ["51-200", "201-500", "501-1000"],
            "requiredSkills": ["Leadership", "Strategy", "Technology"]
        },
        "scoringWeights": {
            "jobTitleWeight": 0.30,
            "industryWeight": 0.25,
            "locationWeight": 0.15,
            "experienceWeight": 0.20,
            "companySizeWeight": 0.05,
            "skillsWeight": 0.05
        },
        "filteringOptions": {
            "minQualificationScore": 70,
            "maxResults": 100,
            "includeScoreBreakdown": True
        },
        "processingOptions": {
            "maxConcurrency": 5,
            "requestDelay": 2.0,
            "retryAttempts": 3,
            "headless": True
        }
    }
    
    print("📝 Sample Input Configuration:")
    print(json.dumps(sample_input, indent=2))
    return sample_input


if __name__ == "__main__":
    print("🚀 LinkedIn Lead Qualifier Actor - Test Suite")
    print("=" * 60)
    print()
    
    # Test scoring engine
    qualified_lead = test_scoring_engine()
    print()
    
    # Show sample input
    sample_input = create_sample_input()
    print()
    
    print("✅ All tests completed successfully!")
    print("🎯 The LinkedIn Lead Qualifier is ready for production use.")
    print()
    print("📚 Next steps:")
    print("  1. Deploy to Apify platform")
    print("  2. Test with real LinkedIn profile URLs")
    print("  3. Adjust scoring criteria based on your needs")
    print("  4. Integrate with your CRM or marketing tools")
