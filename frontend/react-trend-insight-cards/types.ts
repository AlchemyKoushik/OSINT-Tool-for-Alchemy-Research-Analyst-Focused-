export type Trend = {
  id: number;
  title: string;
  description: string;
  examples?: {
    text: string;
    year?: string;
  }[];
  sources: {
    id: number;
    title: string;
    publication?: string;
    year?: string;
    url?: string;
  }[];
};
