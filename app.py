import gradio as gr
import os
import openai
import re
from io import BytesIO
import base64
import requests
from PIL import Image
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv(override=True)
openai_api_key = os.getenv('OPENAI_API_KEY')

system_message = "You are an assistant that analyzes the contents of a company website landing page \
and creates a short brochure about the company for prospective customers, investors and recruits. Respond in markdown."

class Website:
    url: str
    title: str
    text: str

    def __init__(self, url):
        self.url = url
        response = requests.get(url)
        self.body = response.content
        soup = BeautifulSoup(self.body, 'html.parser')
        self.title = soup.title.string if soup.title else "No title found"
        for irrelevant in soup.body(["script", "style", "img", "input"]):
            irrelevant.decompose()
        self.text = soup.body.get_text(separator="\n", strip=True)

    def get_contents(self):
        return f"Webpage Title:\n{self.title}\nWebpage Contents:\n{self.text}\n\n"

# Assuming system_message and Website class are defined elsewhere in your code

def stream_gpt(prompt, model):
    """
    Stream GPT completions and capture the full response.
    
    Args:
        prompt: The user prompt to send to the model
        model: The model to use
        
    Returns:
        A tuple containing (generator, final_result_function)
    """
    messages = [
        {"role": "system", "content": system_message},
        {"role": "user", "content": prompt}
    ]
    
    # Create a mutable container for the result
    result_container = [""]
    
    def get_final_result():
        """Return the current complete result"""
        return result_container[0]
    
    def generator():
        stream = openai.chat.completions.create(
            model=model,
            messages=messages,
            stream=True
        )
        
        for chunk in stream:
            chunk_content = chunk.choices[0].delta.content or ""
            result_container[0] += chunk_content
            yield result_container[0]
    
    return generator(), get_final_result

def generate_brochure_image(brochure_text, style="modern corporate brochure"):
    """
    Generate an image based on the brochure text using OpenAI's GPT Image model.
    
    Args:
        brochure_text: The text content of the brochure
        style: The style description for the image
        
    Returns:
        Base64 encoded image data
    """
    # Create a summarized prompt from the brochure text
    # Limit the text to avoid overwhelming the image generator
    summary = brochure_text[:500] + "..." if len(brochure_text) > 500 else brochure_text
    
    prompt = f"Create a professional {style} based on this company description: {summary}. Incorporate a 3 column layout with minimal colors. I want the output in 2D vector style which can be printed on a brochure."
    
    try:
        response = openai.images.generate(
            model="gpt-image-1",  # Using the specified model
            prompt=prompt,
            n=1,
            quality="high",
            size="1536x1024",
        )
        
        # Return the base64 encoded image data
        return response.data[0].b64_json
    except Exception as e:
        print(f"Error generating image: {e}")
        return None

# Global variable to store the brochure content
current_brochure = {"text": "", "company_name": ""}

def validate_inputs(company_name, url):
    """
    Validate the company name and URL inputs.
    
    Args:
        company_name: Name of the company
        url: URL of the company's landing page
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    if not company_name.strip():
        return False, "Please enter a company name."
    
    # Check if URL starts with http:// or https://
    if not url.strip():
        return False, "Please enter a URL."
    
    url_pattern = re.compile(r'^https?://')
    if not url_pattern.match(url):
        return False, "URL must start with http:// or https://"
    
    return True, ""

def stream_brochure(company_name, url, model):
    """
    Stream a company brochure generation and store the final result in memory.
    
    Args:
        company_name: Name of the company
        url: URL of the company's landing page
        model: Model to use for generation
        
    Returns:
        Generator that yields incremental results for streaming
    """
    global current_brochure
    
    # Validate inputs
    is_valid, error_message = validate_inputs(company_name, url)
    if not is_valid:
        yield f"**Error**: {error_message}"
        return
    
    # If validation passes, proceed with brochure generation
    try:
        yield "Loading website content and generating brochure..."
        
        prompt = f"Please generate a company brochure for {company_name}. Here is their landing page:\n"
        prompt += Website(url).get_contents()
        
        if model == "GPT-4o-mini":
            stream_gen, get_result = stream_gpt(prompt, model="gpt-4o-mini")
        elif model == "GPT-4.1-nano":
            stream_gen, get_result = stream_gpt(prompt, model="gpt-4.1-nano")
        else:
            yield "**Error**: Invalid model selection."
            return
        
        # Stream all partial results
        for partial_result in stream_gen:
            yield partial_result
        
        # Store the final result in memory
        final_result = get_result()
        current_brochure["text"] = final_result
        current_brochure["company_name"] = company_name
        
        # Add a prompt asking if the user wants to generate an image
        yield final_result + "\n\n---\n\nBrochure generation complete. Would you like to generate an image for this brochure? Use the button below to generate."
    
    except Exception as e:
        yield f"**Error**: An unexpected error occurred while generating the brochure: {str(e)}"

def generate_image_from_brochure(generate_image):
    """
    Function to handle the image generation based on user selection.
    
    Args:
        generate_image: Boolean indicating whether to generate an image
        
    Returns:
        Tuple containing (status message, image)
    """
    global current_brochure
    
    if not generate_image:
        return "Image generation canceled.", None
    
    if not current_brochure["text"]:
        return "Please generate a brochure first.", None
    
    # Generate image using the brochure text
    try:
        b64_image = generate_brochure_image(current_brochure["text"], 
                                          style=f"professional company brochure for {current_brochure['company_name']}")
        
        if b64_image:
            try:
                # Convert base64 to image
                image_data = base64.b64decode(b64_image)
                image = Image.open(BytesIO(image_data))
                return f"Image generated successfully for {current_brochure['company_name']} brochure.", image
            except Exception as e:
                return f"Error processing image data: {str(e)}", None
        else:
            return "Failed to generate image. Please try again.", None
    except Exception as e:
        return f"Error during image generation: {str(e)}", None

# Create the Gradio interface
with gr.Blocks() as demo:
    gr.Markdown("# Company Brochure Generator")
    
    with gr.Row():
        with gr.Column():
            company_name = gr.Textbox(label="Company name:")
            url = gr.Textbox(label="Landing page URL including http:// or https://", 
                             placeholder="https://example.com")
            model = gr.Dropdown(["GPT-4o-mini", "GPT-4.1-nano"], 
                                label="Select model", 
                                value="GPT-4o-mini")  # Set default value
            generate_btn = gr.Button("Generate Brochure")
        
    brochure_output = gr.Markdown(label="Brochure:")
    
    with gr.Row():
        generate_img_btn = gr.Button("Generate Image for Brochure")
    
    with gr.Row():
        image_status = gr.Textbox(label="Image Generation Status")
        image_output = gr.Image(label="Brochure Image")
    
    generate_btn.click(
        fn=stream_brochure,
        inputs=[company_name, url, model],
        outputs=brochure_output
    )
    
    generate_img_btn.click(
        fn=generate_image_from_brochure,
        inputs=[gr.Checkbox(value=True, visible=False)],  # Hidden checkbox always set to True
        outputs=[image_status, image_output]
    )

# Launch the interface
if __name__ == "__main__":
    
    # Launch the Gradio app
    demo.launch()