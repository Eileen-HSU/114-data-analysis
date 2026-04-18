// Mock 作品集資料 - 包含單一檔案與資料夾

export const mockFiles = [
  {
    id: "file-001",
    name: "Sales_Q1_2025.csv",
    type: "csv",
    size: "2.4 MB",
    createdAt: "2025-03-10",
    folderId: null,
  },
  {
    id: "file-002",
    name: "Customer_Survey_Results.xlsx",
    type: "xlsx",
    size: "1.8 MB",
    createdAt: "2025-03-15",
    folderId: null,
  },
  {
    id: "file-003",
    name: "Market_Analysis_Report.txt",
    type: "txt",
    size: "0.3 MB",
    createdAt: "2025-03-20",
    folderId: "folder-001",
  },
  {
    id: "file-004",
    name: "Competitor_Data_2025.csv",
    type: "csv",
    size: "3.1 MB",
    createdAt: "2025-03-22",
    folderId: "folder-001",
  },
  {
    id: "file-005",
    name: "User_Behavior_Log.json",
    type: "json",
    size: "5.7 MB",
    createdAt: "2025-04-01",
    folderId: "folder-002",
  },
  {
    id: "file-006",
    name: "Revenue_Forecast.xlsx",
    type: "xlsx",
    size: "1.2 MB",
    createdAt: "2025-04-05",
    folderId: "folder-002",
  },
  {
    id: "file-007",
    name: "Product_Feedback_Raw.txt",
    type: "txt",
    size: "0.8 MB",
    createdAt: "2025-04-08",
    folderId: null,
  },
];

export const mockFolders = [
  {
    id: "folder-001",
    name: "Market Research",
    createdAt: "2025-03-18",
    color: "#6366f1",
  },
  {
    id: "folder-002",
    name: "Product Analytics",
    createdAt: "2025-03-28",
    color: "#10b981",
  },
];
