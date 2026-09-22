"use client";

import { useRouter } from "next/navigation";
import { useApp } from "../../../lib/app-context";
import { RecommendationPage, View } from "../../../lib/shared";

export default function RecommendationsRoute() {
  const router = useRouter();
  const { student, plans, selectedPlan, dataLoading, help } = useApp();
  if (!student) return null;
  const current = plans[selectedPlan] || plans.balanced;
  return (
    <RecommendationPage
      student={student}
      plan={current}
      loading={dataLoading}
      onNavigate={(v: View) => router.push(`/${v}`)}
      onModal={help}
    />
  );
}
