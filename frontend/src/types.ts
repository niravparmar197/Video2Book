// Mirrors backend/api/schemas.py -- keep in sync with that file.

export type BookStatus =
  | 'queued'
  | 'planning'
  | 'outline_ready'
  | 'rendering'
  | 'done'
  | 'failed';

export interface Video {
  video_id: string;
  title: string | null;
  duration_seconds: number | null;
}

export interface Book {
  id: string;
  status: BookStatus;
  pdf_path: string | null;
  error_message: string | null;
  estimated_cost_usd: number;
  url: string;
  created_at: string;
  videos: Video[];
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

export interface ChapterProgress {
  id: string;
  title: string;
  status: 'pending' | 'done';
  score: number | null;
  attempts: number | null;
  passed: boolean | null;
}

export interface PipelineWarning {
  ts: string;
  logger: string;
  message: string;
}

export interface ProgressEvent {
  current_node: string;
  completed_nodes: string[];
  chapters: ChapterProgress[];
  percent: number;
  elapsed_seconds: number;
  warnings: PipelineWarning[];
  /** "Study Notes" / "Podcast Notes" / "Comedy Recap" once decided. */
  book_kind?: string | null;
  /** Seconds each finished pipeline step took, keyed by node name. */
  step_seconds?: Record<string, number>;
}
