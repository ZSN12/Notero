// NoteDetail module types

export interface StudentNote {
  type: string;
  content: string;
}

export interface TranscriptEntry {
  chunk_index: number;
  text: string;
  raw_text?: string;
  display_text?: string;
  timestamps: any[];
  is_corrected?: boolean;
  is_restructured?: boolean;
}

export interface PPTSlide {
  page: number;
  title: string;
  text: string;
  image_path?: string;
  image_base64?: string;
}

export interface PPTData {
  filename: string;
  path: string;
  total_pages: number;
  slides: PPTSlide[];
}

export interface ContentBlock {
  type: 'text' | 'image' | 'marker';
  content?: string;
  src?: string;
  page?: number;
  title?: string;
}

export interface NoteRecord {
  id: string;
  session_id: string;
  content: string;
  transcript?: TranscriptEntry[];
  ppt_images?: PPTData[];
  vocabulary?: any[];
}

export interface SessionRecord {
  id: string;
  title: string;
  summary?: string;
  keywords?: string[];
  duration?: string;
  notebook_id: string;
  date: string;
}

export interface NotebookRecord {
  id: string;
  title: string;
  description?: string;
  icon?: string;
  color?: string;
}
