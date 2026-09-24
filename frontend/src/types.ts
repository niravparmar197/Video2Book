// Mirrors backend/api/schemas.py -- keep in sync with that file.

export type BookStatus =
  | 'queued'
  | 'planning'
  | 'outline_ready'
  | 'rendering'
  | 'done'
  | 'failed';

export interface Book {
  id: string;
  status: BookStatus;
  pdf_path: string | null;
  error_message: string | null;
}

export interface Chapter {
  id: string;
  title: string;
  order: number;
  skip: boolean;
  locked: boolean;
  source_video_ids: string[];
}

export interface ChapterEdit {
  id: string;
  skip: boolean;
  locked: boolean;
}

export interface ProgressEvent {
  current_node: string;
  completed_nodes: string[];
}
