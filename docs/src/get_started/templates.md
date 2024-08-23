# Introduction to templates?

You can create template for all the different types of sessions your host.\
For example: `Car Show`, `Slot Meet`, `Greenville RP Startup`, `ERLC SSU`, `Border RP`, or whatever you want. \
A template defines some key features about that event, such the channel the announcement should be posted to, and a general description of the event. Donut uses webhooks to send the announcement message, so that means you can also define the username and avatar of the webhook that the announcement is sent with.

You can also specify a custom `help` section (also called FAQ). In it, you can include information about your event, and answer questions that you might be anticipating from members. You can also specify custom URL buttons that will be sent with the help/FAQ message. 

Similarly, there is a `parameters` section in the form. Each parameter represents a question that hosts will have to answer when the event starts. These are helpful for clarifying the exact nature of the event being started. For example, if you are a car shows server, you would create a parameter that says `What is the theme?`, and the host would reply with something like `German cars from the 2000s`. The parameter's title, and host's answer will be passed as is into the announcement embed, and will not alter anything about what Donut does.

> [!IMPORTANT]
> Since templates are heavily user-generated content, they must be approved before use. \
> Approval will take a short time, as long as everything inside it follows the [Discord ToS](https://discord.com/archive) and Donut Guidelines.

## How to create a template

Run the command `/events template new`. \
This will send a link. Fill out the form on the link and once your template has been reviewed, it will be available in your server.

> [!INFORMATION]
> The link requires you to sign in using your Discord account. \
> If you sign into a different Discord account than the one used to run the command, you may receive an error.

## The different parts of a template 

This table lists the questions that are in the template form, and what they mean.
| Field | Required | What to input |
---
| Title | Yes | The title of your event. |
| Description | Yes | What your event is about. |
