import { ApiError } from "../api/client";

interface OperationalErrorPresentation {
  readonly message: string;
  readonly nextStep: string;
  readonly title: string;
}

export function presentOperationalError(error: unknown): OperationalErrorPresentation {
  if (error instanceof ApiError) {
    if (error.status === 403)
      return {
        message: "Your account cannot perform this operation.",
        nextStep: "Ask a company administrator or engineer for help.",
        title: "This action is not permitted",
      };
    if (error.status === 404)
      return {
        message: "The item is no longer available in your authorized workspace.",
        nextStep: "Return to the list and choose another item.",
        title: "Item not found",
      };
    if (error.status === 409)
      return {
        message: "This item changed while you were viewing it.",
        nextStep: "Reload the latest state, then try again.",
        title: "The latest state is required",
      };
    if (error.status === 422)
      return {
        message: "One or more required values are missing or invalid.",
        nextStep: "Review the highlighted information and submit again.",
        title: "Check the submitted information",
      };
    if (error.status === 0 || error.status >= 500)
      return {
        message: "The operational service is temporarily unavailable.",
        nextStep: "Keep the current information and try again shortly.",
        title: "Service unavailable",
      };
  }
  return {
    message: "The requested operation could not be completed.",
    nextStep: "Review the current item and try again.",
    title: "Operation unsuccessful",
  };
}
