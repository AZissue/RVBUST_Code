export interface AuthUser {
  id: string;
  username: string;
  name: string;
  email: string | null;
  role: string;
  permissions: string[];
}

declare module 'express-serve-static-core' {
  interface Request {
    user?: AuthUser;
    sessionTokenHash?: string;
  }
}

