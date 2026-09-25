import { notFound } from 'next/navigation';

/** Any unknown path renders the 404 verdict (with a real 404 status). */
export default function Missing() {
  notFound();
}
