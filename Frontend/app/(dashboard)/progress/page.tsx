"use client";

import { useRouter } from "next/navigation";
import { useApp } from "../../../lib/app-context";
import { ProgressPage, View } from "../../../lib/shared";

export default function ProgressRoute() {
  const router = useRouter();
  const { student, completed, completedGrades, courses, history, help } = useApp();
  if (!student) return null;
  return (
    <ProgressPage
      student={student}
      completed={completed}
      grades={completedGrades}
      courses={courses}
      onNavigate={(v: View) => router.push(`/${v}`)}
      history={history}
      onModal={help}
    />
  );
}
