import { redirect } from 'next/navigation';
import { sb } from '@/lib/supabase';

export const dynamic = 'force-dynamic';

export default async function Home() {
  const { data } = await sb.from('sessions').select('token').limit(1);
  const token = data?.[0]?.token;

  if (!token) {
    return <main><h1>No study session is available.</h1></main>;
  }

  redirect(`/run/${token}`);
}
