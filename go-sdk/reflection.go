package gosdk

import (
	"context"
	"fmt"
	"strings"

	"google.golang.org/grpc"
	grpc_reflection_v1alpha "google.golang.org/grpc/reflection/grpc_reflection_v1alpha"
	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/types/descriptorpb"
)

type ReflectionHandle struct {
	endpoint string
	timeout  int
}

type ReflectionClient struct {
	conn   *grpc.ClientConn
	client grpc_reflection_v1alpha.ServerReflectionClient
}

type ServiceInfo struct {
	Name    string
	Methods []MethodInfo
}

type MethodInfo struct {
	Name            string
	InputType       string
	OutputType      string
	ClientStreaming bool
	ServerStreaming bool
}

type MessageInfo struct {
	Name   string
	Fields []FieldInfo
}

type FieldInfo struct {
	Name       string
	Number     int32
	TypeName   string
	IsRepeated bool
	IsRequired bool
	IsOptional bool
}

func NewReflectionHandle(endpoint string) ReflectionHandle {
	return ReflectionHandle{endpoint: endpoint, timeout: DefaultTimeoutSeconds}
}

func (h ReflectionHandle) Connect(ctx context.Context) (*ReflectionClient, error) {
	if h.endpoint == "" {
		return nil, newError(ErrorKindConfiguration, "endpoint is required", nil)
	}
	target, creds, err := dialTargetAndCreds(h.endpoint)
	if err != nil {
		return nil, err
	}
	conn, err := grpc.DialContext(ctx, target, grpc.WithTransportCredentials(creds), grpc.WithBlock())
	if err != nil {
		return nil, newError(ErrorKindConnection, "failed to connect reflection client", err)
	}
	return &ReflectionClient{
		conn:   conn,
		client: grpc_reflection_v1alpha.NewServerReflectionClient(conn),
	}, nil
}

func (h ReflectionHandle) ListServices(ctx context.Context) ([]string, error) {
	rc, err := h.Connect(ctx)
	if err != nil {
		return nil, err
	}
	defer rc.Close()
	return rc.ListServices(ctx)
}

func (h ReflectionHandle) VerifyMarketMakerService(ctx context.Context) (*ServiceInfo, error) {
	rc, err := h.Connect(ctx)
	if err != nil {
		return nil, err
	}
	defer rc.Close()
	return rc.VerifyMarketMakerService(ctx)
}

func (rc *ReflectionClient) Close() error {
	if rc.conn == nil {
		return nil
	}
	return rc.conn.Close()
}

func (rc *ReflectionClient) ListServices(ctx context.Context) ([]string, error) {
	resp, err := rc.singleRequest(ctx, &grpc_reflection_v1alpha.ServerReflectionRequest{
		MessageRequest: &grpc_reflection_v1alpha.ServerReflectionRequest_ListServices{ListServices: ""},
	})
	if err != nil {
		return nil, err
	}
	list := resp.GetListServicesResponse()
	if list == nil {
		return nil, newError(ErrorKindOther, "unexpected reflection response for list services", nil)
	}
	out := make([]string, 0, len(list.Service))
	for _, s := range list.Service {
		out = append(out, s.GetName())
	}
	return out, nil
}

func (rc *ReflectionClient) FileDescriptorBySymbol(ctx context.Context, symbol string) ([]*descriptorpb.FileDescriptorProto, error) {
	resp, err := rc.singleRequest(ctx, &grpc_reflection_v1alpha.ServerReflectionRequest{
		MessageRequest: &grpc_reflection_v1alpha.ServerReflectionRequest_FileContainingSymbol{FileContainingSymbol: symbol},
	})
	if err != nil {
		return nil, err
	}
	return parseFileDescriptorResponse(resp)
}

func (rc *ReflectionClient) FileDescriptorByFilename(ctx context.Context, filename string) ([]*descriptorpb.FileDescriptorProto, error) {
	resp, err := rc.singleRequest(ctx, &grpc_reflection_v1alpha.ServerReflectionRequest{
		MessageRequest: &grpc_reflection_v1alpha.ServerReflectionRequest_FileByFilename{FileByFilename: filename},
	})
	if err != nil {
		return nil, err
	}
	return parseFileDescriptorResponse(resp)
}

func (rc *ReflectionClient) ListMethods(ctx context.Context, serviceName string) ([]string, error) {
	info, err := rc.GetServiceInfo(ctx, serviceName)
	if err != nil {
		return nil, err
	}
	out := make([]string, 0, len(info.Methods))
	for _, m := range info.Methods {
		out = append(out, m.Name)
	}
	return out, nil
}

func (rc *ReflectionClient) GetServiceInfo(ctx context.Context, serviceName string) (*ServiceInfo, error) {
	fds, err := rc.FileDescriptorBySymbol(ctx, serviceName)
	if err != nil {
		return nil, err
	}
	short := serviceName
	if i := strings.LastIndex(serviceName, "."); i >= 0 {
		short = serviceName[i+1:]
	}
	for _, fd := range fds {
		for _, svc := range fd.GetService() {
			if svc.GetName() == short {
				return buildServiceInfo(serviceName, svc), nil
			}
		}
	}
	return nil, newError(ErrorKindOther, fmt.Sprintf("service %q not found in descriptors", serviceName), nil)
}

func (rc *ReflectionClient) GetMessageInfo(ctx context.Context, messageName string) (*MessageInfo, error) {
	fds, err := rc.FileDescriptorBySymbol(ctx, messageName)
	if err != nil {
		return nil, err
	}
	short := messageName
	if i := strings.LastIndex(messageName, "."); i >= 0 {
		short = messageName[i+1:]
	}
	for _, fd := range fds {
		for _, msg := range fd.GetMessageType() {
			if info := findMessageRecursive(short, msg); info != nil {
				return info, nil
			}
		}
	}
	return nil, newError(ErrorKindOther, fmt.Sprintf("message %q not found in descriptors", messageName), nil)
}

func (rc *ReflectionClient) GetAllServiceInfo(ctx context.Context) ([]ServiceInfo, error) {
	names, err := rc.ListServices(ctx)
	if err != nil {
		return nil, err
	}
	services := make([]ServiceInfo, 0, len(names))
	for _, n := range names {
		info, err := rc.GetServiceInfo(ctx, n)
		if err != nil {
			continue
		}
		services = append(services, *info)
	}
	return services, nil
}

func (rc *ReflectionClient) VerifyMarketMakerService(ctx context.Context) (*ServiceInfo, error) {
	services, err := rc.ListServices(ctx)
	if err != nil {
		return nil, err
	}
	for _, s := range services {
		if strings.Contains(s, "MarketMakerIngestionService") {
			return rc.GetServiceInfo(ctx, s)
		}
	}
	return nil, newError(ErrorKindOther, "MarketMakerIngestionService not found via reflection", nil)
}

func (rc *ReflectionClient) singleRequest(ctx context.Context, req *grpc_reflection_v1alpha.ServerReflectionRequest) (*grpc_reflection_v1alpha.ServerReflectionResponse, error) {
	stream, err := rc.client.ServerReflectionInfo(ctx)
	if err != nil {
		return nil, newError(ErrorKindGRPC, "failed to open reflection stream", err)
	}
	if err := stream.Send(req); err != nil {
		return nil, newError(ErrorKindGRPC, "failed to send reflection request", err)
	}
	resp, err := stream.Recv()
	if err != nil {
		return nil, newError(ErrorKindGRPC, "failed to receive reflection response", err)
	}
	_ = stream.CloseSend()
	if e := resp.GetErrorResponse(); e != nil {
		return nil, newError(ErrorKindGRPC, fmt.Sprintf("reflection error code=%d msg=%s", e.GetErrorCode(), e.GetErrorMessage()), nil)
	}
	return resp, nil
}

func parseFileDescriptorResponse(resp *grpc_reflection_v1alpha.ServerReflectionResponse) ([]*descriptorpb.FileDescriptorProto, error) {
	fdr := resp.GetFileDescriptorResponse()
	if fdr == nil {
		return nil, newError(ErrorKindOther, "unexpected reflection response type", nil)
	}
	out := make([]*descriptorpb.FileDescriptorProto, 0, len(fdr.GetFileDescriptorProto()))
	for _, raw := range fdr.GetFileDescriptorProto() {
		fd := &descriptorpb.FileDescriptorProto{}
		if err := proto.Unmarshal(raw, fd); err != nil {
			return nil, newError(ErrorKindOther, "failed to decode file descriptor", err)
		}
		out = append(out, fd)
	}
	return out, nil
}

func buildServiceInfo(name string, svc *descriptorpb.ServiceDescriptorProto) *ServiceInfo {
	methods := make([]MethodInfo, 0, len(svc.GetMethod()))
	for _, m := range svc.GetMethod() {
		methods = append(methods, MethodInfo{
			Name:            m.GetName(),
			InputType:       strings.TrimPrefix(m.GetInputType(), "."),
			OutputType:      strings.TrimPrefix(m.GetOutputType(), "."),
			ClientStreaming: m.GetClientStreaming(),
			ServerStreaming: m.GetServerStreaming(),
		})
	}
	return &ServiceInfo{Name: name, Methods: methods}
}

func findMessageRecursive(name string, msg *descriptorpb.DescriptorProto) *MessageInfo {
	if msg.GetName() == name {
		return buildMessageInfo(msg)
	}
	for _, n := range msg.GetNestedType() {
		if info := findMessageRecursive(name, n); info != nil {
			return info
		}
	}
	return nil
}

func buildMessageInfo(msg *descriptorpb.DescriptorProto) *MessageInfo {
	fields := make([]FieldInfo, 0, len(msg.GetField()))
	for _, f := range msg.GetField() {
		typeName := strings.TrimPrefix(f.GetTypeName(), ".")
		if typeName == "" {
			typeName = strings.ToLower(strings.TrimPrefix(f.GetType().String(), "TYPE_"))
		}
		label := f.GetLabel()
		fields = append(fields, FieldInfo{
			Name:       f.GetName(),
			Number:     f.GetNumber(),
			TypeName:   typeName,
			IsRepeated: label == descriptorpb.FieldDescriptorProto_LABEL_REPEATED,
			IsRequired: label == descriptorpb.FieldDescriptorProto_LABEL_REQUIRED,
			IsOptional: label == descriptorpb.FieldDescriptorProto_LABEL_OPTIONAL,
		})
	}
	return &MessageInfo{Name: msg.GetName(), Fields: fields}
}

func (c *MarketMakerClient) Reflection() ReflectionHandle {
	return NewReflectionHandle(c.config.Endpoint)
}

func (c *MarketMakerClient) ListServices(ctx context.Context) ([]string, error) {
	return c.Reflection().ListServices(ctx)
}

func (c *MarketMakerClient) VerifyService(ctx context.Context) (*ServiceInfo, error) {
	return c.Reflection().VerifyMarketMakerService(ctx)
}
