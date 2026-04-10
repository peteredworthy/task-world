import { Link } from 'react-router-dom';

export function NotFound() {
  return (
    <div className="flex flex-col items-center justify-center py-24 text-center">
      <h1 className="text-2xl font-bold text-text-primary mb-2">Page not found</h1>
      <p className="text-text-muted mb-4">The page you are looking for does not exist.</p>
      <Link
        to="/"
        className="px-4 py-2 text-sm font-medium text-white bg-accent-purple rounded-md hover:bg-accent-purple/80 transition-colors"
      >
        Back to Dashboard
      </Link>
    </div>
  );
}
