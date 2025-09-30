"""Data models for LinkedIn Lead Qualifier."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from datetime import datetime


@dataclass
class QualificationCriteria:
    """Criteria for qualifying LinkedIn leads."""
    
    target_job_titles: List[str] = field(default_factory=list)
    target_industries: List[str] = field(default_factory=list)
    target_locations: List[str] = field(default_factory=list)
    min_experience_years: int = 0
    target_company_sizes: List[str] = field(default_factory=list)
    required_skills: List[str] = field(default_factory=list)


@dataclass
class ScoringWeights:
    """Weights for different scoring criteria."""
    
    job_title_weight: float = 0.25
    industry_weight: float = 0.20
    location_weight: float = 0.15
    experience_weight: float = 0.20
    company_size_weight: float = 0.10
    skills_weight: float = 0.10
    
    def validate(self) -> bool:
        """Validate that weights sum to approximately 1.0."""
        total = (
            self.job_title_weight + self.industry_weight + self.location_weight +
            self.experience_weight + self.company_size_weight + self.skills_weight
        )
        return abs(total - 1.0) < 0.01


@dataclass
class LinkedInProfile:
    """Extracted LinkedIn profile data."""
    
    url: str
    name: Optional[str] = None
    headline: Optional[str] = None
    current_position: Optional[str] = None
    current_company: Optional[str] = None
    location: Optional[str] = None
    industry: Optional[str] = None
    experience_years: Optional[int] = None
    company_size: Optional[str] = None
    skills: List[str] = field(default_factory=list)
    education: List[str] = field(default_factory=list)
    connections: Optional[str] = None
    about: Optional[str] = None
    scraped_at: datetime = field(default_factory=datetime.now)
    
    # Error tracking
    extraction_errors: List[str] = field(default_factory=list)
    is_valid: bool = True


@dataclass
class ScoreBreakdown:
    """Detailed breakdown of qualification scoring."""
    
    job_title_score: float = 0.0
    job_title_match: Optional[str] = None
    
    industry_score: float = 0.0
    industry_match: Optional[str] = None
    
    location_score: float = 0.0
    location_match: Optional[str] = None
    
    experience_score: float = 0.0
    experience_details: Optional[str] = None
    
    company_size_score: float = 0.0
    company_size_match: Optional[str] = None
    
    skills_score: float = 0.0
    skills_matched: List[str] = field(default_factory=list)
    
    total_score: float = 0.0
    qualification_reasons: List[str] = field(default_factory=list)


@dataclass
class QualifiedLead:
    """A qualified lead with profile data and scoring."""
    
    profile: LinkedInProfile
    score_breakdown: ScoreBreakdown
    qualified_at: datetime = field(default_factory=datetime.now)
    
    @property
    def total_score(self) -> float:
        """Get the total qualification score."""
        return self.score_breakdown.total_score
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for dataset output."""
        return {
            # Profile data
            'url': self.profile.url,
            'name': self.profile.name,
            'headline': self.profile.headline,
            'current_position': self.profile.current_position,
            'current_company': self.profile.current_company,
            'location': self.profile.location,
            'industry': self.profile.industry,
            'experience_years': self.profile.experience_years,
            'company_size': self.profile.company_size,
            'skills': self.profile.skills,
            'education': self.profile.education,
            'connections': self.profile.connections,
            'about': self.profile.about,
            
            # Scoring data
            'total_score': self.total_score,
            'job_title_score': self.score_breakdown.job_title_score,
            'job_title_match': self.score_breakdown.job_title_match,
            'industry_score': self.score_breakdown.industry_score,
            'industry_match': self.score_breakdown.industry_match,
            'location_score': self.score_breakdown.location_score,
            'location_match': self.score_breakdown.location_match,
            'experience_score': self.score_breakdown.experience_score,
            'experience_details': self.score_breakdown.experience_details,
            'company_size_score': self.score_breakdown.company_size_score,
            'company_size_match': self.score_breakdown.company_size_match,
            'skills_score': self.score_breakdown.skills_score,
            'skills_matched': self.score_breakdown.skills_matched,
            'qualification_reasons': self.score_breakdown.qualification_reasons,
            
            # Metadata
            'scraped_at': self.profile.scraped_at.isoformat(),
            'qualified_at': self.qualified_at.isoformat(),
            'extraction_errors': self.profile.extraction_errors,
        }


@dataclass
class ProcessingStats:
    """Statistics for the processing run."""
    
    total_profiles: int = 0
    successful_extractions: int = 0
    failed_extractions: int = 0
    qualified_leads: int = 0
    average_score: float = 0.0
    processing_time_seconds: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for logging."""
        return {
            'total_profiles': self.total_profiles,
            'successful_extractions': self.successful_extractions,
            'failed_extractions': self.failed_extractions,
            'qualified_leads': self.qualified_leads,
            'success_rate': self.successful_extractions / max(self.total_profiles, 1) * 100,
            'qualification_rate': self.qualified_leads / max(self.successful_extractions, 1) * 100,
            'average_score': self.average_score,
            'processing_time_seconds': self.processing_time_seconds,
        }
