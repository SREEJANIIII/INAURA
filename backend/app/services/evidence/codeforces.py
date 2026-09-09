import httpx
from typing import List, Dict, Tuple, Optional, Any, Set
from datetime import datetime, timezone

from .base import EvidenceProvider, VerificationResult, ExtractedSignal, EvidenceDepth, VerificationStatus
from .url_utils import validate_platform_url, extract_username_from_path, CODEFORCES_HOSTS
from ..skill_taxonomy import normalize_skill

CODEFORCES_RELIABILITY = 0.85

# Codeforces Rating Benchmarks for algorithmic proficiency calibration
RATING_NEWBIE = 1200
RATING_PUPIL = 1400
RATING_SPECIALIST = 1600
RATING_EXPERT = 1900


class CodeforcesProvider(EvidenceProvider):
    """
    Evidence Intelligence Provider for Codeforces.
    Extracts verifiable competitive programming performance:
    - Official current & peak contest rating
    - Rank / Title (e.g. Pupil, Specialist, Expert, Master)
    - Total rated contest participations
    - Solved problem submissions and topic tags (DP, graphs, greedy, trees, math, binary search)
    Scopes evidence to:
    - Competitive Programming
    - Data Structures & Algorithms
    - Problem Solving
    """

    @property
    def provider_name(self) -> str:
        return "codeforces"

    def can_handle(self, evidence: dict) -> bool:
        etype = (evidence.get("evidence_type") or "").lower()
        url = (evidence.get("source_url") or "").strip()

        if etype == "codeforces":
            if url:
                valid, _, _ = validate_platform_url(url, CODEFORCES_HOSTS)
                return valid
            return True

        if url:
            valid, _, _ = validate_platform_url(url, CODEFORCES_HOSTS)
            return valid

        return False

    def validate(self, evidence: dict) -> Tuple[bool, Optional[str]]:
        url = (evidence.get("source_url") or "").strip()
        if not url:
            return False, "Codeforces URL or handle required"
        valid, path, err = validate_platform_url(url, CODEFORCES_HOSTS)
        if not valid:
            return False, err
        handle = extract_username_from_path(path or "", "codeforces")
        if not handle:
            return False, "Could not extract Codeforces handle from URL"
        return True, None

    async def verify(self, evidence: dict) -> VerificationResult:
        now = datetime.now(timezone.utc)
        url = (evidence.get("source_url") or "").strip()

        # 1. Deterministic offline mock inspection support
        if "mock_inspection" in evidence:
            return self._build_result_from_inspection(evidence["mock_inspection"], now)

        # 2. Validate input and extract handle
        valid, path, err = validate_platform_url(url, CODEFORCES_HOSTS)
        if not valid:
            return VerificationResult(
                status=VerificationStatus.FAILED,
                message=f"Invalid Codeforces URL or handle: {err}",
                provider=self.provider_name,
                raw_metadata={"raw_url": url},
                verified_at=now,
            )

        handle = extract_username_from_path(path or "", "codeforces")
        if not handle:
            return VerificationResult(
                status=VerificationStatus.FAILED,
                message="Could not extract Codeforces handle from provided URL.",
                provider=self.provider_name,
                raw_metadata={"raw_url": url},
                verified_at=now,
            )

        # 3. Query Official Codeforces Public API
        user_info_url = f"https://codeforces.com/api/user.info?handles={handle}"
        rating_history_url = f"https://codeforces.com/api/user.rating?handle={handle}"
        user_status_url = f"https://codeforces.com/api/user.status?handle={handle}&from=1&count=60"
        headers = {
            "User-Agent": "INAURA-Evidence-Intelligence/1.0",
        }

        try:
            async with httpx.AsyncClient(timeout=6.0) as client:
                info_resp = await client.get(user_info_url, headers=headers)

                if info_resp.status_code == 429:
                    return VerificationResult(
                        status=VerificationStatus.FAILED,
                        message="Codeforces API rate limited. Please retry shortly.",
                        provider=self.provider_name,
                        raw_metadata={"handle": handle, "http_status": 429},
                        verified_at=now,
                        warnings=["Rate limited by Codeforces official API"],
                    )

                if info_resp.status_code != 200:
                    return VerificationResult(
                        status=VerificationStatus.FAILED,
                        message=f"Codeforces API returned status {info_resp.status_code}.",
                        provider=self.provider_name,
                        raw_metadata={"handle": handle, "http_status": info_resp.status_code},
                        verified_at=now,
                    )

                data = info_resp.json()
                if data.get("status") != "OK" or not data.get("result"):
                    comment = data.get("comment", "User not found")
                    return VerificationResult(
                        status=VerificationStatus.FAILED,
                        message=f"Codeforces handle '{handle}' not found: {comment}.",
                        provider=self.provider_name,
                        raw_metadata={"handle": handle, "response": data},
                        verified_at=now,
                    )

                user_data = data["result"][0]
                rating = int(user_data.get("rating", 0))
                max_rating = int(user_data.get("maxRating", 0))
                rank = user_data.get("rank", "unrated")
                max_rank = user_data.get("maxRank", "unrated")

                # Query rating history for contest count
                contest_count = 0
                try:
                    rating_resp = await client.get(rating_history_url, headers=headers)
                    if rating_resp.status_code == 200:
                        r_data = rating_resp.json()
                        if r_data.get("status") == "OK" and isinstance(r_data.get("result"), list):
                            contest_count = len(r_data["result"])
                except Exception:
                    pass

                # Query problem submissions for verified problem tags and count
                problem_tags: Dict[str, int] = {}
                solved_problems: Set[str] = set()
                try:
                    status_resp = await client.get(user_status_url, headers=headers)
                    if status_resp.status_code == 200:
                        s_data = status_resp.json()
                        if s_data.get("status") == "OK" and isinstance(s_data.get("result"), list):
                            for sub in s_data["result"]:
                                if sub.get("verdict") == "OK":
                                    prob = sub.get("problem") or {}
                                    prob_id = f"{prob.get('contestId', '')}-{prob.get('index', '')}"
                                    if prob_id not in solved_problems:
                                        solved_problems.add(prob_id)
                                        for t in prob.get("tags", []):
                                            t_clean = t.strip().lower()
                                            problem_tags[t_clean] = problem_tags.get(t_clean, 0) + 1
                except Exception:
                    pass

                inspection = {
                    "handle": handle,
                    "rating": rating,
                    "max_rating": max_rating,
                    "rank": rank,
                    "max_rank": max_rank,
                    "contest_count": contest_count,
                    "solved_count": len(solved_problems),
                    "problem_tags": problem_tags,
                }

                return self._build_result_from_inspection(inspection, now)

        except (httpx.RequestError, Exception) as e:
            return VerificationResult(
                status=VerificationStatus.FAILED,
                message=f"Network connection to Codeforces failed: {str(e)[:100]}",
                provider=self.provider_name,
                raw_metadata={"handle": handle, "error": str(e)},
                verified_at=now,
                warnings=["Network timeout or unreachable Codeforces endpoint"],
            )

    def _build_result_from_inspection(self, facts: dict, verified_at: datetime) -> VerificationResult:
        handle = facts.get("handle") or "user"
        rating = int(facts.get("rating", 0))
        max_rating = int(facts.get("max_rating", 0))
        rank = str(facts.get("rank", "unrated")).lower()
        max_rank = str(facts.get("max_rank", "unrated")).lower()
        contests = int(facts.get("contest_count", 0))
        solved_count = int(facts.get("solved_count", 0))
        problem_tags: Dict[str, int] = facts.get("problem_tags") or {}

        facts_list = [
            f"Codeforces rank '{rank}' (peak '{max_rank}')",
            f"Rating {rating} (max {max_rating}) across {contests} rated contests",
        ]

        if problem_tags:
            top_tags = sorted(problem_tags.keys(), key=lambda k: problem_tags[k], reverse=True)[:5]
            facts_list.append(f"Verified solved problem tags: {', '.join(top_tags)}")
        elif solved_count > 0:
            facts_list.append(f"Verified {solved_count} solved algorithmic problems")

        if rating == 0 and contests == 0 and solved_count == 0 and not problem_tags:
            return VerificationResult(
                status=VerificationStatus.VERIFIED,
                message=f"Verified Codeforces handle '{handle}', but user is unrated with 0 contests or solved problems.",
                provider=self.provider_name,
                signals=[],
                raw_metadata=facts,
                profile={"handle": handle, "rank": rank},
                facts=facts_list,
                warnings=["User has not participated in rated Codeforces contests or solved public problems"],
                verified_at=verified_at,
            )

        # Calibrate proficiency from rating and contest experience
        # Codeforces ratings are exceptionally rigorous:
        # 1200+ (Pupil) is already top 40% of active competitive programmers worldwide
        effective_rating = max(rating, int(max_rating * 0.95))

        if effective_rating < RATING_NEWBIE:
            depth = EvidenceDepth.LEVEL_2_CONFIG
            base_strength = round(0.40 + (max(0, effective_rating - 800) / 400.0) * 0.12, 2)
        elif effective_rating < RATING_PUPIL:
            depth = EvidenceDepth.LEVEL_2_CONFIG
            base_strength = round(0.52 + ((effective_rating - RATING_NEWBIE) / 200.0) * 0.12, 2)
        elif effective_rating < RATING_SPECIALIST:
            depth = EvidenceDepth.LEVEL_3_IMPLEMENTATION
            base_strength = round(0.64 + ((effective_rating - RATING_PUPIL) / 200.0) * 0.11, 2)
        elif effective_rating < RATING_EXPERT:
            depth = EvidenceDepth.LEVEL_4_SUBSTANTIAL
            base_strength = round(0.75 + ((effective_rating - RATING_SPECIALIST) / 300.0) * 0.10, 2)
        else:
            depth = EvidenceDepth.LEVEL_4_SUBSTANTIAL
            # Expert / Master+ is elite algorithmic competency
            base_strength = round(min(0.92, 0.85 + ((effective_rating - RATING_EXPERT) / 600.0) * 0.07), 2)

        base_strength = round(min(0.92, max(0.40, base_strength)), 2)

        signals: List[ExtractedSignal] = []

        # 1. Primary Skill: Competitive Programming
        cp_canonical = normalize_skill("Competitive Programming") or "Competitive Programming"
        signals.append(
            ExtractedSignal(
                skill=cp_canonical,
                signal_strength=base_strength,
                depth=depth,
                reason=(
                    f"Codeforces verified profile '{handle}' has rank '{rank}', "
                    f"current rating {rating} (max {max_rating}) across {contests} rated contests."
                ),
                source_reliability=CODEFORCES_RELIABILITY,
                metadata={
                    "rating": rating,
                    "max_rating": max_rating,
                    "rank": rank,
                    "contest_count": contests,
                },
            )
        )

        # 2. Data Structures & Algorithms (enriched with problem tag breadth)
        dsa_canonical = normalize_skill("Data Structures & Algorithms") or "Data Structures & Algorithms"
        dsa_bonus = 0.02 if len(problem_tags) >= 4 else 0.0
        dsa_strength = round(min(0.92, (base_strength * 0.96) + dsa_bonus), 2)

        dsa_reason = (
            f"Demonstrated complex algorithmic problem solving on Codeforces "
            f"(rating {rating}, {rank}, {contests} contests)."
        )
        if problem_tags:
            top_tags = sorted(problem_tags.keys(), key=lambda k: problem_tags[k], reverse=True)[:4]
            dsa_reason += f" Verified solutions across topics: {', '.join(top_tags)}."

        signals.append(
            ExtractedSignal(
                skill=dsa_canonical,
                signal_strength=dsa_strength,
                depth=depth,
                reason=dsa_reason,
                source_reliability=CODEFORCES_RELIABILITY,
                metadata={
                    "rating": rating,
                    "rank": rank,
                    "solved_count": solved_count,
                    "problem_tags": problem_tags,
                },
            )
        )

        # 3. Problem Solving
        ps_canonical = normalize_skill("Problem Solving") or "Problem Solving"
        ps_strength = round(min(0.88, base_strength * 0.94), 2)
        signals.append(
            ExtractedSignal(
                skill=ps_canonical,
                signal_strength=ps_strength,
                depth=depth,
                reason=f"High-pressure timed algorithmic problem solving verified via Codeforces rating {rating}.",
                source_reliability=CODEFORCES_RELIABILITY,
                metadata={"rating": rating},
            )
        )

        summary_msg = f"Verified Codeforces handle '{handle}': rating {rating} ({rank}, max {max_rating}) across {contests} contests."

        return VerificationResult(
            status=VerificationStatus.VERIFIED,
            message=summary_msg,
            provider=self.provider_name,
            signals=signals,
            raw_metadata=facts,
            profile={"handle": handle, "rank": rank, "rating": rating},
            facts=facts_list,
            verified_at=verified_at,
        )

    async def extract_signals(self, evidence: dict) -> List[ExtractedSignal]:
        res = await self.verify(evidence)
        return res.signals
