type BadgeMessage =
  | { type: "badge_set"; text: string; color: string }
  | { type: "badge_clear" };

chrome.runtime.onMessage.addListener((message: BadgeMessage) => {
  if (message.type === "badge_set") {
    chrome.action.setBadgeText({ text: message.text });
    chrome.action.setBadgeBackgroundColor({ color: message.color });
  } else if (message.type === "badge_clear") {
    chrome.action.setBadgeText({ text: "" });
  }
});
