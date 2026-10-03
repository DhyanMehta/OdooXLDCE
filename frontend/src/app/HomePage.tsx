import { Shell } from "../components/layout/Shell";
import { InitStatus } from "../features/InitStatus";

export function HomePage() {
  return (
    <Shell>
      <header className="hero">
        <p className="hero__eyebrow">Hackathon foundation</p>
        <h1 className="hero__brand">CampusOS</h1>
        <p className="hero__tagline">Student Organization Management Platform.</p>
      </header>
      <InitStatus />
    </Shell>
  );
}
