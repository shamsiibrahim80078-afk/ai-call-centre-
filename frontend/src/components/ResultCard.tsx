import { type ReactNode } from "react";

export function ResultCard({ title, value }: { title: string; value: ReactNode }) {
  return (
    <div className="result-card">
      <span>{title}</span>
      <strong>{value}</strong>
    </div>
  );
}
