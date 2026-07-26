import { useParams } from 'react-router';

export default function HelperPage() {
  const { id } = useParams<{ id: string }>();
  return <div data-page="helper">Helper {id}</div>;
}
