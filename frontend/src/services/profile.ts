import { apiFetch } from "./api";

export type Profile = {
  user_id: string;
  full_name: string;
  college: string;
  degree: string;
  branch: string;
  current_year: string;
  graduation_year: number;
  career_interests: string[];
  hours_per_week: number;
  profile_completed: boolean;
  created_at: string;
  updated_at: string;
};

export type ProfilePayload = Omit<Profile, "user_id" | "profile_completed" | "created_at" | "updated_at">;

export function getProfile() {
  return apiFetch<Profile>("/profile");
}

export function createProfile(payload: ProfilePayload) {
  return apiFetch<Profile>("/profile", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function updateProfile(payload: Partial<ProfilePayload>) {
  return apiFetch<Profile>("/profile", {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}
