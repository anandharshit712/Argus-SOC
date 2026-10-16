// Mock sign-in. No API call: any non-empty username and password is accepted.
// Replace with a real call in src/api/ once the backend has auth.

export type Session = { username: string }

const MOCK_DELAY_MS = 600

export async function signIn(username: string, password: string): Promise<Session> {
  await new Promise((resolve) => setTimeout(resolve, MOCK_DELAY_MS))
  if (!username.trim() || !password) {
    throw new Error('Enter your username and password.')
  }
  return { username: username.trim() }
}
