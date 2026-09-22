"use client";

import { useApp } from "../../../lib/app-context";
import { Profile } from "../../../lib/shared";

export default function ProfileRoute() {
  const { student, courses, completed, completedGrades, saveStudent, help, logout } = useApp();
  if (!student) return null;
  return (
    <Profile
      student={student}
      courses={courses}
      completed={completed}
      initialGrades={completedGrades}
      onSaved={saveStudent}
      onModal={help}
      onLogout={logout}
    />
  );
}
