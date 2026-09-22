"use client";

import { useRouter } from "next/navigation";
import { useApp } from "../../../lib/app-context";
import { PlansPage, View } from "../../../lib/shared";

export default function PlansRoute() {
  const router = useRouter();
  const { plans, selectedPlan, setSelectedPlan, applyPlan, applyingPlan, dataLoading, help } = useApp();
  return (
    <PlansPage
      plans={plans}
      selected={selectedPlan}
      onSelect={setSelectedPlan}
      onApply={applyPlan}
      onNavigate={(v: View) => router.push(`/${v}`)}
      applying={applyingPlan}
      loading={dataLoading}
      onModal={help}
    />
  );
}
