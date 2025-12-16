/**
 * Express authentication middleware
 *
 * Validates Cognito JWT tokens and attaches user context to requests.
 */

import type { Request, Response, NextFunction } from 'express';
import { validateToken, extractBearerToken } from '../auth.js';
import { logger } from '../logger.js';

/**
 * Authentication middleware that validates JWT tokens.
 *
 * Expects Authorization header with format: "Bearer <token>"
 * On success, attaches userContext to the request.
 * On failure, returns 401 Unauthorized.
 */
export async function authMiddleware(
  req: Request,
  res: Response,
  next: NextFunction
): Promise<void> {
  const token = extractBearerToken(req.headers.authorization);

  if (!token) {
    logger.warn('Request missing or invalid Authorization header');
    res.status(401).json({
      error: 'unauthorized',
      message: 'Missing or invalid Authorization header',
    });
    return;
  }

  try {
    const userContext = await validateToken(token);
    req.userContext = userContext;
    logger.debug(`Authenticated user: ${userContext.email}`);
    next();
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Token validation failed';
    logger.warn(`Token validation failed: ${message}`);
    res.status(401).json({
      error: 'unauthorized',
      message: 'Invalid or expired token',
    });
  }
}

/**
 * Middleware to require authenticated user context.
 * Use after authMiddleware to ensure userContext exists.
 */
export function requireAuth(
  req: Request,
  res: Response,
  next: NextFunction
): void {
  if (!req.userContext) {
    res.status(401).json({
      error: 'unauthorized',
      message: 'Authentication required',
    });
    return;
  }
  next();
}
