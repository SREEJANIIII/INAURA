import { Link, useLocation } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import Button from "../components/ui/app-button";
import "./NotFound.css";

/** A wrong address: say so plainly, and offer the one link most likely to be wanted */
export default function NotFound() {
  const { user } = useAuth();
  const { pathname } = useLocation();

  return (
    <main className="nf">
      <p className="nf__code">404</p>
      <h1 className="nf__title">This page doesn’t exist</h1>
      <p className="nf__text">
        Nothing lives at <code>{pathname}</code>. The link may be old, or the address mistyped.
      </p>
      <div className="nf__actions">
        {user ? (
          <>
            <Button asChild variant="primary" size="lg"><Link to="/career-track">Go to your Career Track</Link></Button>
            <Button asChild variant="secondary" size="lg"><Link to="/analysis">Your evidence</Link></Button>
          </>
        ) : (
          <>
            <Button asChild variant="primary" size="lg"><Link to="/">Go to INAURA</Link></Button>
            <Button asChild variant="secondary" size="lg"><Link to="/login">Log in</Link></Button>
          </>
        )}
      </div>
    </main>
  );
}
