import { z } from 'zod';

export const LoginRequestSchema = z.object({
  identifier: z.string().min(1, 'Email or username is required.'),
  password: z.string().min(8, 'Password must be at least 8 characters.'),
});

export const RegisterRequestSchema = z.object({
  email: z.email('Enter a valid email address.'),
  username: z
    .string()
    .min(3, 'Username must be at least 3 characters.')
    .max(30, 'Username must be at most 30 characters.')
    .regex(
      /^[a-z0-9_-]+$/,
      'Username may only contain lowercase letters, digits, hyphens, and underscores.',
    ),
  password: z.string().min(8, 'Password must be at least 8 characters.'),
});
