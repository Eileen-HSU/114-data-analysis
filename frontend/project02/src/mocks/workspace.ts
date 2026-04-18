// Mock Workspace 歷史對話紀錄

export const mockSessions = [
  {
    id: "session-001",
    title: "Sales Q1 Analysis",
    createdAt: "2025-04-10",
    messages: [
      {
        id: "msg-001",
        role: "user",
        content: "Please analyze the sales trend from Q1 2025 data.",
        timestamp: "2025-04-10T09:00:00",
      },
      {
        id: "msg-002",
        role: "assistant",
        content:
          "Based on the Q1 2025 sales data, I can see a 23% growth compared to Q4 2024. The top performing categories are Electronics (+34%) and Home Appliances (+28%). There is a notable dip in February which correlates with the supply chain disruption reported in week 6.",
        timestamp: "2025-04-10T09:00:05",
      },
    ],
  },
  {
    id: "session-002",
    title: "Customer Survey Insights",
    createdAt: "2025-04-08",
    messages: [
      {
        id: "msg-003",
        role: "user",
        content: "Summarize the key findings from the customer survey.",
        timestamp: "2025-04-08T14:30:00",
      },
      {
        id: "msg-004",
        role: "assistant",
        content:
          "The customer survey reveals that 78% of respondents are satisfied with the product quality. The main pain points are delivery time (mentioned by 45%) and customer support response speed (38%). NPS score is 62, which is above industry average.",
        timestamp: "2025-04-08T14:30:08",
      },
    ],
  },
  {
    id: "session-003",
    title: "Market Competitor Report",
    createdAt: "2025-04-05",
    messages: [
      {
        id: "msg-005",
        role: "user",
        content: "Compare our market position with competitors.",
        timestamp: "2025-04-05T11:00:00",
      },
    ],
  },
];

// 當前活躍 session 的 mock 訊息
export const mockCurrentMessages = [
  {
    id: "cur-001",
    role: "assistant",
    content:
      "Hello! I am your data analysis assistant. Please upload a file or type your question to get started. I support CSV, Excel, JSON, and plain text formats.",
    timestamp: "2025-04-12T10:00:00",
  },
];
