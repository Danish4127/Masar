"use client";

import { useApp } from "../../../lib/app-context";
import { Catalog } from "../../../lib/shared";

export default function CatalogRoute() {
  const { courses, selectedCourses, setSelectedCourses, savedSelection, setSavedSelection, completed, completedGrades, help } = useApp();
  return (
    <Catalog
      courses={courses}
      selected={selectedCourses}
      setSelected={setSelectedCourses}
      savedSelection={savedSelection}
      setSavedSelection={setSavedSelection}
      completed={completed}
      completedGrades={completedGrades}
      onModal={help}
    />
  );
}
