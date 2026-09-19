import { useParams } from "react-router-dom";
import ClassificationList from "../shared/ClassificationList";

export default function ReviewPanel() {
  const { topicKey } = useParams();
  return <ClassificationList topicParam={topicKey} />;
}
