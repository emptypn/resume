# Install: pip install weasyprint

from weasyprint import HTML, CSS
import yaml
from jinja2 import Environment, FileSystemLoader


def render_html(yaml_path, template_path, output_path):
    # Load YAML content
    with open(yaml_path, 'r', encoding='utf-8') as yaml_file:
        data = yaml.safe_load(yaml_file)

    # Set up Jinja2 environment
    env = Environment(loader=FileSystemLoader('.'))
    template = env.get_template(template_path)

    # Render the template with data
    output = template.render(**data)

    # Write to output HTML file
    with open(output_path, 'w', encoding='utf-8') as output_file:
        output_file.write(output)

    print(f"HTML rendered to {output_path}")


def html_to_pdf_single_page(html_file, output_pdf):
    """
    Convert HTML to PDF as one long continuous page
    """
    html = HTML(filename=html_file)

    css_1cm = [CSS(string="@page {width: 210mm; height: 1cm; page-break-inside: always;}}}")]
    render = html.render(stylesheets=css_1cm)
    css = CSS(string="@page {width: 210mm; height: " + str(len(render.pages)) + "cm}}}")
    html.write_pdf(output_pdf, stylesheets=[css])


def html_to_pdf_printable(html_file, output_pdf, scale):
    """
    Convert HTML to PDF as one long continuous page
    """
    html = HTML(filename=html_file)
    css = CSS(string=f"""
            html, body {{
                font-size: {10 * scale}pt !important;
                line-height: 1.4;
            }}

            h1 {{ font-size: {18 * scale}pt !important; margin-bottom: {8 * scale}pt; }}
            h2 {{ font-size: {14 * scale}pt !important; margin-bottom: {6 * scale}pt; }}
            h3 {{ font-size: {12 * scale}pt !important; margin-bottom: {5 * scale}pt; }}
            h4 {{ font-size: {11 * scale}pt !important; margin-bottom: {4 * scale}pt; }}

            p, li, span, div, td, th {{
                font-size: {10 * scale}pt !important;
            }}

            .contact, .testimonial {{
                font-size: {9 * scale}pt !important;
            }}

            /* Hide UI elements */
            .download-btn {{
                display: none !important;
            }}

            @page {{
                size: A4;
                margin: 15mm;
            }}
        """)
    html.write_pdf(output_pdf, stylesheets=[css])


def main():
    try:
        print("Rendering HTML...")
        render_html("resume.yaml", "resume.html.template", "index.html")
        output_pdf = 'David_Elkind_Resume.pdf'
        print("Rendering single-page PDF...")
        html_to_pdf_single_page('index.html', output_pdf)
        print("Rendering printable PDF...")
        html_to_pdf_printable('index.html', f'Printable_{output_pdf}', 0.9)
        print(f"PDFs generated...")
    except Exception as e:
        print(f"Error: {str(e)}")


if __name__ == "__main__":
    main()
