"""Lead qualification scoring engine with configurable weights and detailed breakdowns."""

from __future__ import annotations

import re
from typing import List, Optional, Tuple
from fuzzywuzzy import fuzz

from .models import (
    LinkedInProfile,
    QualificationCriteria,
    ScoringWeights,
    ScoreBreakdown,
    QualifiedLead,
)


class LeadScoringEngine:
    """Engine for scoring LinkedIn profiles against qualification criteria."""
    
    def __init__(
        self,
        criteria: QualificationCriteria,
        weights: ScoringWeights,
    ):
        self.criteria = criteria
        self.weights = weights
        
        # Validate weights
        if not weights.validate():
            raise ValueError("Scoring weights must sum to approximately 1.0")
    
    def score_profile(self, profile: LinkedInProfile) -> ScoreBreakdown:
        """Score a LinkedIn profile against qualification criteria."""
        breakdown = ScoreBreakdown()
        
        # Score job title
        breakdown.job_title_score, breakdown.job_title_match = self._score_job_title(profile)
        
        # Score industry
        breakdown.industry_score, breakdown.industry_match = self._score_industry(profile)
        
        # Score location
        breakdown.location_score, breakdown.location_match = self._score_location(profile)
        
        # Score experience
        breakdown.experience_score, breakdown.experience_details = self._score_experience(profile)
        
        # Score company size
        breakdown.company_size_score, breakdown.company_size_match = self._score_company_size(profile)
        
        # Score skills
        breakdown.skills_score, breakdown.skills_matched = self._score_skills(profile)
        
        # Calculate total weighted score
        breakdown.total_score = (
            breakdown.job_title_score * self.weights.job_title_weight +
            breakdown.industry_score * self.weights.industry_weight +
            breakdown.location_score * self.weights.location_weight +
            breakdown.experience_score * self.weights.experience_weight +
            breakdown.company_size_score * self.weights.company_size_weight +
            breakdown.skills_score * self.weights.skills_weight
        ) * 100  # Convert to 0-100 scale
        
        # Generate qualification reasons
        breakdown.qualification_reasons = self._generate_qualification_reasons(breakdown)
        
        return breakdown
    
    def qualify_lead(self, profile: LinkedInProfile, min_score: float = 60.0) -> Optional[QualifiedLead]:
        """Score and qualify a lead if it meets the minimum threshold."""
        if not profile.is_valid:
            return None
        
        score_breakdown = self.score_profile(profile)
        
        if score_breakdown.total_score >= min_score:
            return QualifiedLead(
                profile=profile,
                score_breakdown=score_breakdown,
            )
        
        return None
    
    def _score_job_title(self, profile: LinkedInProfile) -> Tuple[float, Optional[str]]:
        """Score job title match."""
        if not self.criteria.target_job_titles or not profile.current_position:
            return 0.0, None
        
        current_title = profile.current_position.lower()
        best_match = None
        best_score = 0.0
        
        for target_title in self.criteria.target_job_titles:
            target_lower = target_title.lower()
            
            # Exact match gets full score
            if target_lower in current_title or current_title in target_lower:
                return 1.0, target_title
            
            # Fuzzy matching for partial matches
            fuzzy_score = fuzz.partial_ratio(current_title, target_lower) / 100.0
            if fuzzy_score > best_score:
                best_score = fuzzy_score
                best_match = target_title
        
        # Only return matches above 70% similarity
        if best_score >= 0.7:
            return best_score, best_match
        
        return 0.0, None
    
    def _score_industry(self, profile: LinkedInProfile) -> Tuple[float, Optional[str]]:
        """Score industry match."""
        if not self.criteria.target_industries:
            return 0.0, None
        
        # Check both industry field and headline/about for industry keywords
        text_to_check = []
        if profile.industry:
            text_to_check.append(profile.industry.lower())
        if profile.headline:
            text_to_check.append(profile.headline.lower())
        if profile.about:
            text_to_check.append(profile.about.lower())
        
        if not text_to_check:
            return 0.0, None
        
        combined_text = ' '.join(text_to_check)
        best_match = None
        best_score = 0.0
        
        for target_industry in self.criteria.target_industries:
            target_lower = target_industry.lower()
            
            # Check for exact or partial matches
            if target_lower in combined_text:
                return 1.0, target_industry
            
            # Fuzzy matching
            for text in text_to_check:
                fuzzy_score = fuzz.partial_ratio(text, target_lower) / 100.0
                if fuzzy_score > best_score:
                    best_score = fuzzy_score
                    best_match = target_industry
        
        if best_score >= 0.7:
            return best_score, best_match
        
        return 0.0, None
    
    def _score_location(self, profile: LinkedInProfile) -> Tuple[float, Optional[str]]:
        """Score location match."""
        if not self.criteria.target_locations or not profile.location:
            return 0.0, None
        
        profile_location = profile.location.lower()
        best_match = None
        best_score = 0.0
        
        for target_location in self.criteria.target_locations:
            target_lower = target_location.lower()
            
            # Check for exact or partial matches
            if target_lower in profile_location or profile_location in target_lower:
                return 1.0, target_location
            
            # Special handling for remote work
            if target_lower == 'remote' and any(
                keyword in profile_location 
                for keyword in ['remote', 'worldwide', 'global', 'distributed']
            ):
                return 1.0, target_location
            
            # Fuzzy matching for city/region names
            fuzzy_score = fuzz.partial_ratio(profile_location, target_lower) / 100.0
            if fuzzy_score > best_score:
                best_score = fuzzy_score
                best_match = target_location
        
        if best_score >= 0.8:  # Higher threshold for location matching
            return best_score, best_match
        
        return 0.0, None
    
    def _score_experience(self, profile: LinkedInProfile) -> Tuple[float, Optional[str]]:
        """Score experience level."""
        if not profile.experience_years:
            return 0.0, "Experience not available"
        
        min_years = self.criteria.min_experience_years
        actual_years = profile.experience_years
        
        if actual_years >= min_years:
            # Give full score if meets minimum, bonus for more experience
            base_score = 1.0
            bonus = min(0.2, (actual_years - min_years) * 0.02)  # Up to 20% bonus
            final_score = min(1.0, base_score + bonus)
            
            details = f"{actual_years} years (meets {min_years}+ requirement)"
            if bonus > 0:
                details += f" with {bonus*100:.0f}% experience bonus"
            
            return final_score, details
        else:
            # Partial score for less experience
            score = actual_years / max(min_years, 1) * 0.7  # Max 70% for under-qualified
            details = f"{actual_years} years (below {min_years} requirement)"
            return score, details
    
    def _score_company_size(self, profile: LinkedInProfile) -> Tuple[float, Optional[str]]:
        """Score company size match."""
        if not self.criteria.target_company_sizes or not profile.company_size:
            return 0.0, None
        
        # This would need enhancement with actual company size data
        # For now, return neutral score
        return 0.5, "Company size data not available"
    
    def _score_skills(self, profile: LinkedInProfile) -> Tuple[float, List[str]]:
        """Score skills match."""
        if not self.criteria.required_skills or not profile.skills:
            return 0.0, []
        
        matched_skills = []
        profile_skills_lower = [skill.lower() for skill in profile.skills]
        
        for required_skill in self.criteria.required_skills:
            required_lower = required_skill.lower()
            
            # Check for exact matches
            if required_lower in profile_skills_lower:
                matched_skills.append(required_skill)
                continue
            
            # Check for partial matches in profile skills
            for profile_skill in profile_skills_lower:
                if (required_lower in profile_skill or 
                    fuzz.partial_ratio(profile_skill, required_lower) >= 80):
                    matched_skills.append(required_skill)
                    break
        
        # Score based on percentage of required skills matched
        if self.criteria.required_skills:
            score = len(matched_skills) / len(self.criteria.required_skills)
            return min(1.0, score), matched_skills
        
        return 0.0, []
    
    def _generate_qualification_reasons(self, breakdown: ScoreBreakdown) -> List[str]:
        """Generate human-readable qualification reasons."""
        reasons = []
        
        # Job title reasons
        if breakdown.job_title_score > 0.7:
            reasons.append(f"Strong job title match: {breakdown.job_title_match}")
        elif breakdown.job_title_score > 0.3:
            reasons.append(f"Partial job title match: {breakdown.job_title_match}")
        
        # Industry reasons
        if breakdown.industry_score > 0.7:
            reasons.append(f"Target industry match: {breakdown.industry_match}")
        elif breakdown.industry_score > 0.3:
            reasons.append(f"Related industry: {breakdown.industry_match}")
        
        # Location reasons
        if breakdown.location_score > 0.8:
            reasons.append(f"Perfect location match: {breakdown.location_match}")
        elif breakdown.location_score > 0.5:
            reasons.append(f"Good location match: {breakdown.location_match}")
        
        # Experience reasons
        if breakdown.experience_score > 0.8:
            reasons.append(f"Excellent experience level: {breakdown.experience_details}")
        elif breakdown.experience_score > 0.5:
            reasons.append(f"Good experience level: {breakdown.experience_details}")
        elif breakdown.experience_score > 0:
            reasons.append(f"Some experience: {breakdown.experience_details}")
        
        # Skills reasons
        if breakdown.skills_matched:
            if len(breakdown.skills_matched) == 1:
                reasons.append(f"Has required skill: {breakdown.skills_matched[0]}")
            else:
                reasons.append(f"Has {len(breakdown.skills_matched)} required skills: {', '.join(breakdown.skills_matched[:3])}")
        
        # Overall score assessment
        if breakdown.total_score >= 80:
            reasons.append("Excellent overall qualification match")
        elif breakdown.total_score >= 60:
            reasons.append("Good qualification match")
        elif breakdown.total_score >= 40:
            reasons.append("Moderate qualification match")
        else:
            reasons.append("Limited qualification match")
        
        return reasons
