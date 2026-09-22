"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useApp } from "../../lib/app-context";
import { Auth, BootScreen, Modal } from "../../lib/shared";

export default function SignupPage() {
  const router = useRouter();
  const { courses, student, checkingSession, authenticated, help, modal, closeModal } = useApp();

  useEffect(() => {
    if (!checkingSession && student) router.replace("/catalog");
  }, [checkingSession, student, router]);

  if (checkingSession || student) return <BootScreen />;

  return (
    <>
    <Auth
      courses={courses}
      initialMode="signup"
      onSwitchMode={(m) => router.push(m === "signup" ? "/signup" : "/login")}
      onAuthenticated={async (s, completedCodes, initialPlans, grades) => {
        authenticated(s, completedCodes, initialPlans, grades);
        router.prefetch("/catalog");
        router.prefetch("/recommendations");
        router.prefetch("/plans");
        router.prefetch("/progress");
        router.prefetch("/profile");
        router.push("/catalog");
      }}
      onHelp={help}
    />
    {modal && <Modal title={modal.title} onClose={closeModal}>{modal.body}</Modal>}
    </>
  );
}
